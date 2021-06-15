import asyncio
import json
import logging
from pathlib import Path
import sys
import webbrowser
import re
import pickle
import os

from bs4 import BeautifulSoup
from galaxy.api.plugin import Plugin, create_and_run_plugin
from galaxy.api.consts import Platform, LicenseType, OSCompatibility
from galaxy.api.types import NextStep, Authentication, Game, LicenseInfo
from galaxy.api.errors import AuthenticationRequired

from http_client import HTTPClient
from pip._vendor.distlib._backport import shutil

with open(Path(__file__).parent / 'manifest.json', 'r') as f:
    __version__ = json.load(f)['version']

DOWNLOAD_LINKS_KEY = "download_links"

Indiegala_os = {
    'win': OSCompatibility.Windows,
    'lin': OSCompatibility.Linux,
    'mac': OSCompatibility.MacOS,
}

Supported_os = {
    'win32': 'win',
    'linux': 'lin',
    'darwin': 'mac'
}

END_URI_REGEX = r"^https://www\.indiegala\.com/?(#.*)?$"

AUTH_PARAMS = {
    "window_title": "Login to Indiegala",
    "window_width": 1000,
    "window_height": 800,
    "start_uri": f"https://www.indiegala.com/login",
    "end_uri_regex": END_URI_REGEX,
}

# To hopefully be shown when either the IP check or the Captcha appears
SECURITY_AUTH_PARAMS = {
    "window_title": "Indiegala Security Check",
    "window_width": 1000,
    "window_height": 800,
    "start_uri": f"https://www.indiegala.com/library",
    "end_uri_regex": END_URI_REGEX,
}

SECURITY_JS = {r"^https://www\.indiegala\.com/.*": [
    r'''
        if (document.getElementsByTagName('title')[0].text.includes("Library | Indiegala")) {
            window.location.href = "/";
        }
    '''
]}  # Redirects to the homepage if the library loads normally

SHOWCASE_URL = 'https://www.indiegala.com/library/showcase/%s'

HOMEPAGE = 'https://www.indiegala.com'

API_USER_INFO = "https://2-dot-main-service-dot-indiegala-prod.appspot.com/login_new/user_info"
API_PRODUCT_INFO = "https://developers-service-dot-indiegala-prod.appspot.com/get_product_info?prod_name=%s&dev_id=%s"

PLUGIN_FILE_PATH = os.path.dirname(os.path.realpath(__file__))
DATA_CACHE_FILE_PATH = PLUGIN_FILE_PATH + '/data_cache'
LOCAL_GAMES_CACHE = DATA_CACHE_FILE_PATH + '/games.dict'
LOCAL_URL_CACHE = DATA_CACHE_FILE_PATH + '/url.dict'
LOCAL_USERINFO_CACHE = DATA_CACHE_FILE_PATH+'/user.dict'


class IndieGalaPlugin(Plugin):
    def __init__(self, reader, writer, token):
        super().__init__(
            Platform.IndieGala,
            __version__,
            reader,
            writer,
            token
        )
        self.http_client = HTTPClient(self.store_credentials)
        self.session_cookie = None
        self.download_links = self.persistent_cache.get(DOWNLOAD_LINKS_KEY)
        if not self.download_links:
            self.download_links = {}

        os.makedirs(name=DATA_CACHE_FILE_PATH, exist_ok=True)

    async def shutdown(self):
        await self.http_client.close()

    async def authenticate(self, stored_credentials=None):
        if not stored_credentials:
            return NextStep("web_session", AUTH_PARAMS)
        self.http_client.update_cookies(stored_credentials)

        try:
            return await self.get_user_auth()
        except AuthenticationRequired:
            return NextStep("web_session", SECURITY_AUTH_PARAMS, cookies=self.http_client.get_next_step_cookies(), js=SECURITY_JS)

    async def pass_login_credentials(self, step, credentials, cookies):
        """Called just after CEF authentication (called as NextStep by authenticate)"""
        session_cookies = {cookie['name']: cookie['value']
                           for cookie in cookies if cookie['name']}
        self.http_client.update_cookies(session_cookies)
        try:
            return await self.get_user_auth()
        except AuthenticationRequired:
            return NextStep("web_session", SECURITY_AUTH_PARAMS, cookies=self.http_client.get_next_step_cookies(), js=SECURITY_JS)

    async def get_product_info(self, prod_name, dev_id):
        resp = await self.http_client.get(API_PRODUCT_INFO % (prod_name, dev_id))
        return json.loads(resp)

    async def get_owned_games(self):
        info = await self.get_user_info()
        games = info["showcase_content"]["content"]["user_collection"]
        owned_games = []

        for game in games:
            game_info = await self.get_product_info(
                game['prod_slugged_name'], game['prod_dev_namespace'])
            product_data = game_info['product_data']
            owned_games.append(Game(
                game_id=product_data['prod_slugged_name'],
                game_title=product_data['name'],
                license_info=LicenseInfo(LicenseType.SinglePurchase),
                dlcs=[]
            ))
            self.download_links[product_data['prod_slugged_name']
                                ] = product_data["downloadable_versions"]

        self.persistent_cache[DOWNLOAD_LINKS_KEY] = self.download_links
        self.push_cache()

        return owned_games

    def load_local_cache(self, path):
        try:
            with open(path, 'rb') as cache:
                data = pickle.load(cache)
                logging.debug("loaded from local cache")
                return data
        except:
            logging.debug("no local game cache found")
            return []

    def save_local_cache(self, path, data):
        try:
            with open(path, 'wb+') as cache:
                pickle.dump(data, cache)
            logging.debug("saved to local cache")
        except:
            raise

    async def get_user_info(self):
        resp = await self.http_client.get(API_USER_INFO)

        info = json.loads(resp)
        if info['user_found'] == 'false':
            raise AuthenticationRequired

        return info

    async def get_user_auth(self):
        info = await self.get_user_info()
        username = info['_indiegala_username']
        return Authentication(username, username)

    async def retrieve_showcase_html(self, n=1):
        return await self.http_client.get(SHOWCASE_URL % n)

    async def get_os_compatibility(self, game_id, context):
        cache = self.download_links
        compat = OSCompatibility(0)

        if not game_id in cache:
            return

        cache = cache[game_id]

        for os_name in ['win', 'lin', 'mac']:
            if os_name in cache:
                compat = compat | Indiegala_os[os_name]

        return compat

    async def launch_game(self, game_id: str) -> None:
        pass

    async def install_game(self, game_id: str) -> None:
        logging.debug('Installing %s', game_id)
        game_links = self.download_links[game_id]
        logging.debug(game_links)
        url = game_links[Supported_os[sys.platform]]
        logging.debug('Launching %s', url)
        webbrowser.open(url)

    def delete_cache(self):
        logging.info("Delete local cache: " + DATA_CACHE_FILE_PATH)
        shutil.rmtree(DATA_CACHE_FILE_PATH, True)
        pass

    async def _shutdown(self):
        self.delete_cache()
        await super()._shutdown()

    def tick(self):
        if not self.get_owned_games:
            self.get_owned_games()
        if not self.get_os_compatibility:
            self.get_os_compatibility()

    @staticmethod
    def parse_html_into_games(soup):
        games = soup.select('a.library-showcase-title')
        for game in games:
            game_name = str(game.string)
            game_href = game['href']
            url_slug = str(game_href.split('indiegala.com/')[1])
            logging.debug('Parsed %s, %s', game_name, url_slug)
            yield Game(
                game_id=url_slug,
                game_title=game_name,
                license_info=LicenseInfo(LicenseType.SinglePurchase),
                dlcs=[]
            )


def main():
    create_and_run_plugin(IndieGalaPlugin, sys.argv)


# run plugin event loop
if __name__ == "__main__":
    main()
