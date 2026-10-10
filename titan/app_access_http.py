"""Browser handoff and the narrow Docker-to-Titan app authorization endpoint."""
from http.cookies import SimpleCookie
import urllib.parse
from .app_access import app_id, cookie_name, upstream_cookies
from .core import Error
from .identity import require_application


class AppAccessHTTPMixin:
    def app_access_get(self, path, query):
        if path not in ('/api/app-open', '/apps/internal/redeem', '/apps/internal/verify'):
            return False
        if self.app.demo:
            raise Error('Geschützte App-Anmeldung ist in der Demo nicht aktiv.', 409)
        app = app_id(query.get('app'))
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get('Cookie', ''))
        except Exception:
            raise Error('Ungültige App-Anmeldung.', 401) from None
        if path == '/api/app-open':
            self.origin_check()
            user = self.require_user()
            require_application(self.app.store, user, 'apps')
            if set(query) != {'app'} or 'titan_session' not in cookies:
                raise Error('App in Titan erneut öffnen.', 401)
            info = self.app.agent.call('app_gateway_info', app=app)
            host = urllib.parse.urlsplit(self.request_origin()).hostname
            if not host or type(info.get('port')) is not int or not 1024 <= info['port'] <= 65535 or info.get('scheme') != 'http':
                raise Error('App-Adresse ist nicht verfügbar.', 503)
            host = '[' + host + ']' if ':' in host else host
            origin = 'http://' + host + ':' + str(info['port'])
            ticket = self.app.app_access.issue(app, cookies['titan_session'].value, origin)
            self.send_headers(303, 0, extra={'Location': origin + '/_titan/authorize?ticket=' + ticket,
                                           'Referrer-Policy': 'no-referrer'})
            return True
        # The caller chooses no host, port or filesystem path. Every grant is
        # app-bound, and an uninstalled package immediately loses access.
        self.app.agent.call('app_gateway_info', app=app)
        if path == '/apps/internal/redeem':
            if set(query) != {'app', 'ticket'}:
                raise Error('Ungültiger App-Link.')
            token = self.app.app_access.redeem(app, query['ticket'])
            self.send_headers(303, 0, extra={'Location': '/', 'Referrer-Policy': 'no-referrer',
                'Set-Cookie': cookie_name(app) + '=' + token + '; HttpOnly; SameSite=Lax; Path=/'})
            return True
        if set(query) != {'app'} or cookie_name(app) not in cookies:
            raise Error('App in Titan öffnen, um dich anzumelden.', 401)
        user = self.app.app_access.authorize(app, cookies[cookie_name(app)].value)
        origin = self.headers.get('Origin')
        method = self.headers.get('X-Forwarded-Method', 'GET')
        upgrade = self.headers.get('Upgrade', '').lower() == 'websocket'
        cross_resource = (self.headers.get('Sec-Fetch-Site') in ('cross-site', 'same-site') and
                          self.headers.get('Sec-Fetch-Mode') != 'navigate')
        if cross_resource or origin and origin != user['app_origin'] or (method not in ('GET', 'HEAD', 'OPTIONS') or upgrade) and not origin:
            raise Error('App-Anfrage stammt nicht von diesem Zugang.', 403)
        self.send_headers(204, 0, extra={'X-Titan-Upstream-Cookie': upstream_cookies(self.headers.get('Cookie', ''))})
        return True
