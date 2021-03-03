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
        self.download_links = self.load_local_cache(LOCAL_URL_CACHE)
        if not self.download_links:
            self.download_links = {}

        os.makedirs(name=DATA_CACHE_FILE_PATH, exist_ok=True)

    async def shutdown(self):
        await self.http_client.close()

    # implement methods
    async def authenticate(self, stored_credentials=None):
        if self.load_local_cache(LOCAL_USERINFO_CACHE):
            return await self.get_user_info()

        if not stored_credentials:
            return NextStep("web_session", AUTH_PARAMS)
        self.http_client.update_cookies(stored_credentials)
        return await self.get_user_info()

    async def pass_login_credentials(self, step, credentials, cookies):
        if self.load_local_cache(LOCAL_USERINFO_CACHE):
            return await self.get_user_info()

        """Called just after CEF authentication (called as NextStep by authenticate)"""
        session_cookies = {cookie['name']: cookie['value']
                           for cookie in cookies if cookie['name']}
        self.http_client.update_cookies(session_cookies)
        return await self.get_user_info()

    async def get_owned_games(self):
        games = self.load_local_cache(LOCAL_GAMES_CACHE)
        if games:
            return games

        page = 1
        while True:
            raw_html = await self.retrieve_showcase_html(page)

            if 'Your showcase list is actually empty.' in raw_html:
                self.save_local_cache(LOCAL_GAMES_CACHE, games)
                self.save_local_cache(LOCAL_URL_CACHE, self.download_links)
                return games

            if 'Profile locked' in raw_html:
                logging.debug('IP check required')
                self.lost_authentication()
                raise AuthenticationRequired()

            if '_Incapsula_Resource' in raw_html:
                logging.debug('Incapsula challenge on showcase page %s', page)
                self.lost_authentication()
                raise AuthenticationRequired()

            soup = BeautifulSoup(raw_html)
            games.extend(self.parse_html_into_games(soup))
            self.parse_download_url(soup)
            page += 1

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

    def parse_download_url(self, soup):
        links = soup.select('.library-showcase-download-btn')
        cache = self.download_links

        for link in links:
            url = re.search(r"'(.*)'", link['onclick']).groups()[0]
            game_id, supported_os = url.split("/")[-1].split(".")[0].split("_")
            game_download_links = cache.get(game_id, {})
            game_download_links[supported_os] = url
            cache[game_id] = game_download_links

        self.persistent_cache[DOWNLOAD_LINKS_KEY] = self.download_links
        self.push_cache()

    async def get_user_info(self):
        username = self.load_local_cache(LOCAL_USERINFO_CACHE)
        if not username:
            text = await self.http_client.get(HOMEPAGE)

            if '_Incapsula_Resource' in text:
                logging.debug('Incapsula challenge on get_user_info')
                # TODO try returning a NextStep() to open a browser. Can I open a next step to /library?
                raise AuthenticationRequired()
            if 'Profile locked' in text:
                logging.debug('IP check required')

            soup = BeautifulSoup(text)
            username_div = soup.select('div.username-text')[0]
            username = str(username_div.string)
            self.save_local_cache(LOCAL_USERINFO_CACHE, username)
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
