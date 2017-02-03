import logging
import json
import os
import signal
import sys
from urllib.parse import parse_qs, urlencode

# from multiprocessing import Process
import requests

sys.path.insert(0, os.path.abspath(os.path.realpath(__file__) + '/../../../'))

from oauth2 import Provider
from oauth2.error import UserNotAuthenticated
from oauth2.grant import AuthorizationCodeGrant
from oauth2.tokengenerator import Uuid4
from oauth2.store.memory import ClientStore, TokenStore
from oauth2.web import AuthorizationCodeGrantSiteAdapter
from oauth2.web.tornado import OAuth2Handler
from tornado.ioloop import IOLoop
from tornado.web import Application, url
from wsgiref.simple_server import make_server, WSGIRequestHandler


logging.basicConfig(level=logging.DEBUG)


class ClientRequestHandler(WSGIRequestHandler):
    """
    Request handler that enables formatting of the log messages on the console.

    This handler is used by the client application.
    """
    def address_string(self):
        return "client app"


class OAuthRequestHandler(WSGIRequestHandler):
    """
    Request handler that enables formatting of the log messages on the console.

    This handler is used by the python-oauth2 application.
    """
    def address_string(self):
        return "python-oauth2"


class TestSiteAdapter(AuthorizationCodeGrantSiteAdapter):
    """
    This adapter renders a confirmation page so the user can confirm the auth
    request.
    """

    CONFIRMATION_TEMPLATE = """
<html>
    <body>
        <p>
            <a href="{url}&confirm=1">confirm</a>
        </p>
        <p>
            <a href="{url}&confirm=0">deny</a>
        </p>
    </body>
</html>
    """

    def render_auth_page(self, request, response, environ, scopes, client):
        url = request.path + "?" + request.query_string
        response.body = self.CONFIRMATION_TEMPLATE.format(url=url).encode('utf8')

        return response

    def authenticate(self, request, environ, scopes, client):
        print(request, environ, scopes, client)
        import IPython
        IPython.embed()
        if request.method == "GET":
            if request.get_param("confirm") == "1":
                return
        raise UserNotAuthenticated

    def user_has_denied_access(self, request):
        if request.method == "GET":
            if request.get_param("confirm") == "0":
                return True
        return False


class ClientApplication(object):
    """
    Very basic application that simulates calls to the API of the
    python-oauth2 app.
    """
    callback_url = "http://localhost:9999/callback"
    client_id = "abc"
    client_secret = "xyz"
    api_server_url = "http://localhost:8765/hub/api/oauth2"

    def __init__(self):
        self.access_token = None
        self.auth_token = None
        self.token_type = ""

    def __call__(self, env, start_response):
        if env["PATH_INFO"] == "/app":
            status, body, headers = self._serve_application(env)
        elif env["PATH_INFO"] == "/callback":
            status, body, headers = self._read_auth_token(env)
        else:
            status = "301 Moved"
            body = ""
            headers = {"Location": "/app"}

        start_response(status,
                       list(headers.items()))
        return body

    def _request_access_token(self):
        print("Requesting access token...")

        post_params = {"client_id": self.client_id,
                       "client_secret": self.client_secret,
                       "code": self.auth_token,
                       "grant_type": "authorization_code",
                       "redirect_uri": self.callback_url}
        token_endpoint = self.api_server_url + "/token"
        print('token endpoint', token_endpoint)

        resp = requests.post(token_endpoint, data=urlencode(post_params).encode('utf8'),
                        headers={
                            'Authorization': 'token oauth_secret',
                            'Content-Type': 'application/x-www-form-urlencoded',
                        })

        result = resp.json()
        if "error" in result:
            print("Error!", result)
            return "500 Server Error", [resp.content], {'Content-Type': 'application/json'}
        
        self.access_token = result["access_token"]
        self.token_type = result["token_type"]

        confirmation = "Received access token '%s' of type '%s'" % (self.access_token, self.token_type)
        print(confirmation)
        return "302 Found", "", {"Location": "/app"}

    def _read_auth_token(self, env):
        print("Receiving authorization token...")

        query_params = parse_qs(env["QUERY_STRING"])

        if "error" in query_params:
            location = "/app?error=" + query_params["error"][0]
            return "302 Found", "", {"Location": location}

        self.auth_token = query_params["code"][0]

        print("Received temporary authorization token '%s'" % (self.auth_token,))

        return "302 Found", "", {"Location": "/app"}

    def _request_auth_token(self):
        print("Requesting authorization token...")

        auth_endpoint = self.api_server_url + "/authorize"
        query = urlencode({"client_id": "abc",
                                  "redirect_uri": self.callback_url,
                                  "response_type": "code"})

        location = "%s?%s" % (auth_endpoint, query)

        return "302 Found", "", {"Location": location}

    def _serve_application(self, env):
        query_params = parse_qs(env["QUERY_STRING"])

        if ("error" in query_params
                and query_params["error"][0] == "access_denied"):
            return "200 OK", ["User has denied access"], {}

        if self.access_token is None:
            if self.auth_token is None:
                return self._request_auth_token()
            else:
                return self._request_access_token()
        else:
            confirmation = "Current access token '%s' of type '%s'" % (self.access_token, self.token_type)
            return "200 OK", [confirmation.encode('utf8')], {}


def run_app_server():
    app = ClientApplication()

    try:
        httpd = make_server('', 9999, app, handler_class=ClientRequestHandler)

        print("Starting Client app on http://localhost:9999/...")
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.server_close()


def run_auth_server():
    client_store = ClientStore()
    client_store.add_client(client_id="abc", client_secret="xyz",
                            redirect_uris=["http://localhost:9999/callback"])

    token_store = TokenStore()

    provider = Provider(access_token_store=token_store,
                        auth_code_store=token_store, client_store=client_store,
                        token_generator=Uuid4())
    provider.add_grant(AuthorizationCodeGrant(site_adapter=TestSiteAdapter()))

    try:
        app = Application([
            url(provider.authorize_path, OAuth2Handler, dict(provider=provider)),
            url(provider.token_path, OAuth2Handler, dict(provider=provider)),
        ])

        app.listen(8080)
        print("Starting OAuth2 server on http://localhost:8080/...")
        IOLoop.current().start()

    except KeyboardInterrupt:
        IOLoop.current().close()


def main():
    run_app_server()
    return
    # app_server = Thread(target=run_app_server)
    # app_server.start()
    # auth_server = Process(target=run_auth_server)
    # auth_server.start()
    print("Access http://localhost:9999/app in your browser")

    # def sigint_handler(signal, frame):
    #     print("Terminating servers...")
    #     # auth_server.terminate()
    #     # auth_server.join()
    #     app_server.terminate()
    #     app_server.join()
    #
    #
    # signal.signal(signal.SIGINT, sigint_handler)
    run_auth_server()

if __name__ == "__main__":
    main()
