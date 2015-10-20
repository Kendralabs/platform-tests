#
# Copyright (c) 2015 Intel Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import argparse
import configparser
import os


__all__ = ["update_test_config", "parse_arguments", "CONFIG"]

# secrets config
__SECRETS = configparser.ConfigParser()
__SECRETS.read(os.path.join("test_utils", "secrets", ".secret.ini"))
# configuration variables depending on the environment
__CONFIG = configparser.ConfigParser()
__CONFIG.read_string("""
    [DEFAULT]
        admin_username = trusted.analytics.tester@gmail.com
        login.do_scheme = http
        ssl_validation = False
        reference_org = seedorg
        reference_space = seedspace
    [gotapaas.eu]
        login.do_scheme = https
        ssl_validation = True
    [demo-gotapaas.com]
        ssl_validation = True
    [52.20.52.106.xip.io]
        reference_org = sato
        reference_space = dev
""")


# current test settings - set values constant for all environments
CONFIG = {
    "github_auth": (__SECRETS["github"]["username"], __SECRETS["github"]["password"]),
    "ssh_key_passphrase": __SECRETS["ssh"].get("passphrase", ""),
    "test_user_email": "intel.data.tests@gmail.com"
}


def update_test_config(domain=None, proxy=None, client_type=None):
    defaults = __CONFIG.defaults()
    defaults.update(__SECRETS.defaults())
    if domain is not None:
        CONFIG["domain"] = domain
        CONFIG["admin_username"] = __CONFIG.get(domain, "admin_username", fallback=defaults["admin_username"])
        CONFIG["admin_password"] = __SECRETS.get(domain, CONFIG["admin_username"],
                                                 fallback=defaults[CONFIG["admin_username"]])
        CONFIG["login_token"] = __SECRETS.get(domain, "login_token", fallback=defaults["login_token"])
        CONFIG["login.do_scheme"] = __CONFIG.get(domain, "login.do_scheme", fallback=defaults["login.do_scheme"])
        CONFIG["ssl_validation"] = __CONFIG.getboolean(domain, "ssl_validation",
                                                       fallback=__CONFIG.getboolean("DEFAULT", "ssl_validation"))
    CONFIG["proxy"] = proxy
    if client_type is not None:
        CONFIG["client_type"] = client_type


# update settings using default values
update_test_config(domain="daily-gotapaas.com",
                   proxy="proxy-mu.intel.com:911",
                   client_type="console")
# update settings using environment variables (when tests are run with PyCharm runner)
update_test_config(domain=os.environ.get("TEST_ENVIRONMENT"),
                   proxy=os.environ.get("TEST_PROXY"),
                   client_type=os.environ.get("TEST_CLIENT_TYPE"))


def parse_arguments():
    parser = argparse.ArgumentParser(description="Platform API Automated Tests")
    parser.add_argument("-e", "--environment",
                        help="environment where tests are to be run, e.g. gotapaas.eu",
                        required=True)
    parser.add_argument("--proxy",
                        default=None,
                        help="set proxy for api client")
    parser.add_argument("-t", "--test",
                        default=None,
                        help="a group of tests to execute")
    parser.add_argument("--client-type",
                        default="console",
                        choices=["console", "app"],
                        help="choose a client type for tests")
    parser.add_argument("-u", help="obsolete argument")
    return parser.parse_args()
