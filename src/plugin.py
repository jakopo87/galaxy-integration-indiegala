from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
import sys
from typing import Any, Dict, List
import webbrowser

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


class IndieGalaPlugin(Plugin):
    def __init__(self, reader, writer, token):
        super().__init__(
            Platform.IndieGala,
            __version__,
            reader,
            writer,
            token
        )
        self.__owned_games: Dict[str, IndieGalaGame] = {}
        self.http_client = HTTPClient(self.store_credentials)
        self.session_cookie = None
        self.download_links = self.persistent_cache.get(DOWNLOAD_LINKS_KEY)
        if not self.download_links:
            self.download_links = {}

    async def shutdown(self):
        await self.http_client.close()

    async def authenticate(self, stored_credentials=None):
        if not stored_credentials:
            return NextStep("web_session", AUTH_PARAMS)

        try:
            return await self.get_user_auth()
        except AuthenticationRequired:
            return NextStep("web_session", SECURITY_AUTH_PARAMS, cookies=self.http_client.get_next_step_cookies(), js=SECURITY_JS)

    async def pass_login_credentials(self, step, credentials, cookies):
        """Called just after CEF authentication (called as NextStep by authenticate)"""
        session_cookies = {cookie['name']: cookie['value']
                           for cookie in cookies if cookie['name']}
        self.http_client.update_cookies(session_cookies)
        self.store_credentials(session_cookies)
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

        for game in games:
            self.__owned_games[game['prod_slugged_name']] = IndieGalaGame(
                game_id=game['prod_slugged_name'],
                game_title=game['prod_name'],
                license_info=LicenseInfo(LicenseType.SinglePurchase),
                dlcs=[],
                dev_id=game['prod_dev_namespace']
            )
        return list(self.__owned_games.values())

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

    async def prepare_os_compatibility_context(self, game_ids: List[str]) -> Any:
        for game_id in game_ids:
            game = self.__owned_games[game_id]
            if not game:
                continue

            game_info = await self.get_product_info(game.game_id, game.dev_id)

            game.download_links = game_info['downloadable_versions']

    async def get_os_compatibility(self, game_id, context):
        compat = OSCompatibility(0)
        game = self.__owned_games[game_id]

        if not game.download_links:
            return compat

        for os_name in ['win', 'lin', 'mac']:
            if os_name in game.download_links:
                compat = compat | Indiegala_os[os_name]

        return compat

    async def launch_game(self, game_id: str) -> None:
        logging.debug('Launching %s', game_id)

    async def install_game(self, game_id: str) -> None:
        logging.debug('Installing %s', game_id)

        game = self.__owned_games[game_id]
        if not game:
            return

        url = game.download_links[Supported_os[sys.platform]]
        # HACK: incorrect url reported from api
        url = url.replace("https://content.indiegalacdn.com/",
                          "https://content.indiegalacdn.com/DevShowcaseBuildsVolume/")

        logging.debug('Download %s', url)

        webbrowser.open(url)


@dataclass
class IndieGalaGame(Game):
    dev_id: str
    download_links: Dict[str, str] = field(default_factory=lambda: {})


def main():
    create_and_run_plugin(IndieGalaPlugin, sys.argv)


# run plugin event loop
if __name__ == "__main__":
    main()
