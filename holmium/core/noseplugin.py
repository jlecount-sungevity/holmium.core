"""
nose plugin for holmium (or the other way around? :P)
"""
from contextlib import closing
import os
import pdb
import traceback
import sys
import json
import tempfile
from random import random
from nose.plugins.base import Plugin
from nose.plugins.skip import SkipTest
from selenium.common.exceptions import UnexpectedAlertPresentException, WebDriverException
from .config import HolmiumConfig, Config, BROWSER_MAPPING
from .env import ENV, LazyWebDriverList
from holmium.core.env import LazyWebDriver
from .logger import log

# pylint: disable=invalid-name
try:
    from fresher import ftc
except ImportError:  # pragma: no cover
    ftc = None  # pragma: no cover


def load_source(name, path):
    """
    abstracted out for 2.7 versus 3.x support
    """
    if sys.version_info >= (3, 0, 0):
        # pylint: disable=no-name-in-module
        from importlib import machinery  # pragma: no cover

        loader = machinery.SourceFileLoader(name, path)  # pragma: no cover
        return loader.load_module(name)  # pragma: no cover
    else:
        import imp  # pragma: no cover

        return imp.load_source(name, path)  # pragma: no cover


class HolmiumNose(Plugin):
    """
    nose plugin to allow bootstrapping testcases with a selenium driver
    """
    name = "holmium"
    enabled = False

    def __init__(self):
        Plugin.__init__(self)
        self.config = {}
        self.environment = None
        self.logger = log

    def options(self, parser, env):
        """
        Register command line options
        """
        parser.add_option("", "--with-holmium", dest="ho_enabled",
                          action="store_true",
                          help="use holmium to setup test case environment")
        parser.add_option("", "--holmium-environment", dest="ho_env",
                          help="environment to pass to holmium test case"
                               "configuration")
        parser.add_option("", "--holmium-config-dir", dest="ho_config_dir",
                          help="configuration directory that contains config.py or config.json"
                               "configuration")
        parser.add_option("", "--holmium-browser", dest="ho_browser",
                          type="choice",
                          choices=list(
                              BROWSER_MAPPING.keys()),
                          help="the selenium driver to invoke")
        parser.add_option("", "--holmium-remote", dest="ho_remote",
                          help="full url to remote selenium instance")
        parser.add_option("", "--holmium-capabilities", dest="ho_cap",
                          help="json dictionary of extra capabilities")
        parser.add_option("", "--holmium-useragent", dest="ho_ua",
                          help="User-agent string to use. Only available"
                               "for firefox & chrome")
        parser.add_option("", "--holmium-ignore-ssl-errors",
                          action="store_true", dest="ho_ignore_ssl",
                          help="Ignore ssl errors while running tests")
        parser.add_option("", "--holmium-browser-per-test",
                          action="store_true", dest="ho_fresh_instance",
                          help="Create a fresh browser per test class",
                          default=False)

    def configure(self, options, conf):
        if options.ho_enabled:
            browser = options.ho_browser or os.environ.get("HO_BROWSER", "")
            environment = options.ho_env or os.environ.get("HO_ENVIRONMENT", "")
            remote_url = options.ho_remote or os.environ.get("HO_REMOTE", "")
            user_agent = options.ho_ua or os.environ.get("HO_USERAGENT", "")
            config_dir = options.ho_config_dir or os.environ.get("HO_CONFIG_DIR", "")
            fresh_instance = options.ho_fresh_instance or bool(int(os.environ.get("HO_BROWSER_PER_TEST", 0)))
            ignore_ssl = options.ho_ignore_ssl or os.environ.get(
                "HO_IGNORE_SSL_ERRORS", False)
            if options.ho_cap and os.path.isfile(options.ho_cap):
                caps = json.loads(open(options.ho_cap).read())
            else:
                caps = options.ho_cap and json.loads(options.ho_cap) or {}
            # pylint: disable=attribute-defined-outside-init
            self.holmium_config = holmium_config = HolmiumConfig(browser,
                                                                 remote_url,
                                                                 caps,
                                                                 config_dir,
                                                                 user_agent,
                                                                 environment,
                                                                 ignore_ssl,
                                                                 fresh_instance)
            # pylint:disable=no-member,attribute-defined-outside-init
            driver_cls = BROWSER_MAPPING.get(holmium_config.browser, None)
            if holmium_config.remote:
                if holmium_config.browser == 'android':
                    driver_cls = BROWSER_MAPPING["android"]
                elif holmium_config.browser == 'iphone':
                    driver_cls = BROWSER_MAPPING["iphone"]
                else:
                    driver_cls = BROWSER_MAPPING["remote"]

            self.driver = LazyWebDriver(driver_cls, holmium_config)
            self.enabled = True

    # pylint: disable=invalid-name
    def beforeTest(self, test):
        """
        setup the initialization for the driver, and load the config
        """
        if not ("driver" in ENV and ENV["driver"] == self.driver):
            ENV["driver"] = self.driver
        if not "drivers" in ENV:
            ENV["drivers"] = LazyWebDriverList()
        if not hasattr(test.test, "feature"):
            base_file = test.address()[0]
        else:
            base_file = test.test.feature.src_file
        config_path = self.holmium_config.config_dir or os.path.join(os.path.split(base_file)[0], "config")
        try:
            config = None

            if os.path.isfile(os.path.join(config_path, "config.json")):
                with closing(open(os.path.join(config_path, "config.json"))) as config_file:
                    config = json.loads(config_file.read())
            elif os.path.isfile(os.path.join(config_path, "config.py")):
                if "holmium_testcase_config" in sys.modules:
                    del sys.modules["holmium_testcase_config"]
                config = load_source("holmium_testcase_config",
                                     os.path.join(config_path, "config.py")).config
            if config:
                self.config = Config(config, {
                    "holmium": self.holmium_config})
        except Exception as exc:
            self.logger.debug("unable to load %s" % config_path)
            raise SkipTest(
                "error in loading config file at path %s" % config_path, exc)
        if HolmiumNose.is_freshen_test(test) and ftc:
            ftc.config = self.config
        else:
            setattr(test.test.__class__, "config", self.config)

    # pylint:disable=invalid-name,no-self-use
    def startTest(self, test):
        """
        before each test set the self.driver/self.drivers attribute
        for the test.
        """
        if ENV.get("driver", None):
            if HolmiumNose.is_freshen_test(test) and ftc:
                ftc.driver = ENV["driver"]
                ftc.drivers = ENV["drivers"]
            else:
                setattr(test.test.__class__, "driver", ENV["driver"])
                setattr(test.test.__class__, "drivers", ENV["drivers"])

    def afterTest(self, _):
        """
        run after the test completes. kill the browser or just clear
        cookies depending on config
        """
        # pylint:disable=no-member

        is_local_mode = 'remote' not in self.holmium_config and self.holmium_config['remote']
        random_str = str(random()).replace('.', '')
        if os.path.exists("logs"):
            output_dir = "logs"
        else:
            output_dir = tempfile.gettempdir()
        snapfile = os.path.join(output_dir, "screenshot_{0}.png".format(random_str))

        # JL: Working around an issue in which holmium_config is unset on the test class.
        if ENV.get("driver", None):
            if hasattr(self, 'holmium_config'):
                if self.holmium_config.fresh_instance:
                    for driver in ENV["drivers"]:
                        driver.safe_quit()
            else:
                print "WARNING: holmium_config unset on {0}".format(self)

        elif ENV.get("driver"):
            for driver in ENV["drivers"]:
                try:
                    if is_local_mode: # if we're running locally, take snapshots.  If not, sauce handles it.
                        # upon test exit, take screenshot before teardown, then delete if there's no error here
                        driver.save_screenshot(snapfile)
                        driver.safe_clear()
                        os.remove(snapfile)
                    else:
                        driver.safe_clear()
                except UnexpectedAlertPresentException:
                    alert = driver.switch_to_alert()
                    text = alert.text
                    raise UnexpectedAlertPresentException(text)
                except Exception as e:
                    if is_local_mode:
                        print "Got exception {0}.  Screenshot to be found in {1}".format(e, snapfile)
                    else:
                        raise e

    @staticmethod
    def is_freshen_test(test):
        """
        checks for tell tale signs of being a fresher test
        """
        return test.address()[1] == "fresher.noseplugin"
