import ipaddress
import logging
import requests
import json
import urllib.parse

import urllib3
from requests.exceptions import SSLError

from lib import Registry
from lib.session import Session
from lib.space import Space
from lib.vdp import VDP


class ManagerException(Exception):
    pass


class ManagerRpcCall:

    def __init__(self, url):
        self._baseurl = url

    @classmethod
    def get_proxy(cls, url):
        urldata = urllib3.util.parse_url(url)
        try:
            ip = ipaddress.ip_address(urldata.host)
        except Exception:
            ip = None
        if urldata.host.endswith(".lthn"):
            proxy = True
        elif ip and ip in ipaddress.ip_network("100.64.0.0/10"):
            proxy = True
        else:
            proxy = None
        if proxy:
            proxy = {"http": "http://127.0.0.1:8080", "https": "http://127.0.0.1:8080"}
        return proxy

    def parse_response(self, response):
        return json.loads(response)

    def get_payment_url(self, wallet: str, paymentid: str) -> [str, bool]:
        r = requests.get(
            self._baseurl + "/api/pay/stripe?wallet=%s&paymentid=%s" % (
              urllib.parse.quote(wallet), urllib.parse.quote(paymentid)),
            proxies=self.get_proxy(self._baseurl)
        )
        if r.status_code == 200:
            return r.text
        else:
            logging.getLogger("client").error("Cannot get payment link: %s (%s)" % (r.status_code, r.text))
            return False

    def create_session(self, gate, space: Space, days, prepare_data=None):
        session = Session()
        session.generate(gate.get_id(), space.get_id(), days)
        # Create fake session just for initializing data
        data = {"gateid": gate.get_id(), "spaceid": space.get_id(), "days": session.days()}
        if prepare_data:
            data.update(prepare_data)
        try:
            r = requests.post(
                self._baseurl + "/api/session",
                headers={"Content-Type": "application/json"},
                json=data,
                proxies=self.get_proxy(self._baseurl)
            )
        except SSLError:
            try:
                r = requests.post(
                    self._baseurl + "/api/session",
                    headers={"Content-Type": "application/json"},
                    json=data,
                    cert=gate.get_cafile(Registry.cfg.tmp_dir),
                    proxies=self.get_proxy(self._baseurl)
                )
            except SSLError as e:
                raise ManagerException("%s -- %s" % (self._baseurl, e))
        if r.status_code == 200 or r.status_code == 402 or r.status_code == 465:
            return self.parse_response(r.text)
        else:
            raise ManagerException("%s -- %s" % (self._baseurl, r.text))

    def get_session_info(self, session):
        r = requests.get(
            self._baseurl + "/api/session?sessionid=%s" % urllib.parse.quote(session.get_id()),
            proxies=self.get_proxy(self._baseurl)
        )
        if r.status_code == 200 or r.status_code == 402:
            return self.parse_response(r.text)
        elif r.status_code == 404:
            return None
        else:
            raise ManagerException("%s -- %s" % (self._baseurl, r.text))

    def rekey_session(self, session, public_key):
        if session.get_gate().get_type() == "wg":
            r = requests.get(
                self._baseurl + "/api/session/rekey?sessionid=%s&wg_public_key=%s" % (
                    urllib.parse.quote(session.get_id()), urllib.parse.quote(public_key)),
                proxies=self.get_proxy(self._baseurl)
            )
            if r.status_code == 200:
                logging.getLogger("vdp").info("Session %s rekeyed." % session.get_id())
                return self.parse_response(r.text)
            elif r.status_code == 404:
                logging.getLogger("vdp").error("Session %s to rekey is not anymore on server." % session.get_id())
                return False
            else:
                raise ManagerException("%s -- %s/%s" % (self._baseurl, r.status_code, r.text))
        else:
            raise ManagerException("%s -- %s" % (self._baseurl, "Not a WG session for rekey"))

    def reuse_session(self, session, days=None):
        if not days:
            days = session.days()
        r = requests.get(
            self._baseurl + "/api/session/reuse?sessionid=%s&days=%s" % (
                urllib.parse.quote(session.get_id().encode("utf-8")), days),
            proxies=self.get_proxy(self._baseurl)
        )
        if r.status_code == 402:
            return self.parse_response(r.text)
        else:
            raise ManagerException("%s -- %s" % (self._baseurl, r.text))

    def push_vdp(self, vdp: VDP):
        vdp_jsn = vdp.get_json()
        try:
            r = requests.post(
                self._baseurl + "/api/vdp",
                data=vdp_jsn,
                proxies=self.get_proxy(self._baseurl)
            )
            if r.status_code == 200:
                return r.text
            else:
                raise ManagerException(r.text)
        except requests.RequestException as r:
            raise ManagerException("%s -- %s" % (self._baseurl, str(r)))

    def fetch_vdp(self):
        try:
            r = requests.get(
                self._baseurl + "/api/vdp",
                proxies=self.get_proxy(self._baseurl)
            )
            if r.status_code == 200:
                return r.text
            else:
                raise ManagerException(r.text)
        except requests.RequestException as r:
            raise ManagerException("%s -- %s" % (self._baseurl, str(r)))
