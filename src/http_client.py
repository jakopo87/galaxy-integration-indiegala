import logging

import aiohttp
from galaxy.api.errors import AuthenticationRequired
from galaxy.api.types import Cookie
from galaxy.http import create_client_session
from yarl import URL


class CookieJar(aiohttp.CookieJar):
    # Inspired by https://github.com/TouwaStar/Galaxy_Plugin_Bethesda/blob/master/betty/http_client.py
    def __init__(self):
        super().__init__()


class HTTPClient(object):
    """
    Intended to store and track cookies and update them on each request
    """

    def __init__(self):
        self.cookiejar = CookieJar()

        headers = {
            'User-Agent': 'galaClient'
        }

        self.session = create_client_session(
            cookie_jar=self.cookiejar, headers=headers)

    async def post(self, url, payload):
        self.session.post(url, data=payload)

    async def get(self, url):
        """
        returns the url and updates the cookies
        :param url:
        :return:
        """

        logging.debug('Calling HTTPClient.get with %s', url)
        response = await self.session.get(url)
        text = await response.text()
        if '_Incapsula_Resource' in text:
            logging.debug('Incapsula challenge on request for %s', url)
            raise AuthenticationRequired()
        if 'Profile locked' in text:
            logging.debug('IP check required on request for %s', url)
            raise AuthenticationRequired()
        return text

    def update_cookies(self, cookies):
        self.cookiejar.update_cookies(cookies)

    def get_next_step_cookies(self):
        return [Cookie(cookie.key, cookie.value) for cookie in self.cookiejar]

    async def close(self):
        await self.session.close()
