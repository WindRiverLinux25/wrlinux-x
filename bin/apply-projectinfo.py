#!/usr/bin/env python3
#
# Copyright (C) 2025 Wind River Systems, Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA 02111-1307 USA

import os
import sys
import time
import argparse
import logging
import json
import shutil
import subprocess
import shlex
import logger_setup
from urllib.parse import urlparse

def correct_project_path(file, project_path):
    subprocess.run(['sed', '-i', '-e', 's#/PROJECT_TOPDIR#%s#g' % project_path, file], check=True)

def remove_user_password(cmd):
    args = shlex.split(cmd)
    result = []

    skip_next = False
    for value in args:
        if skip_next:
            skip_next = False
            continue

        if value.startswith("--user=") or value.startswith("--password="):
            continue

        if value == "--user" or value == "--password":
            skip_next = True
            continue

        result.append(value)

    return " ".join(shlex.quote(x) for x in result)

class ApplyProjectinfo(object):
    """
    * Apply project with input projectinfo tarball
        - setup the project
        - build target if target exist
    """

    def __init__(self):
        parser = argparse.ArgumentParser(description="apply-projectinfo.py: Application to apply project with tarball which is created by create-projectinfo.py")
        parser.add_argument("-d", "--debug", help = "Enable debug output",
            action="store_const", const=logging.DEBUG, dest="loglevel", default=logging.INFO)
        parser.add_argument('-p', '--apply-path', default = os.getcwd(), help='Specify project apply path (Default: current directory)')
        parser.add_argument('-t', '--tarball', required = True, help='Specify path of the projectinfo tarball')
        parser.add_argument('--base-url', metavar="URL", help='Specify URL to fetch from')
        parser.add_argument('--base-branch', metavar="BRANCH", help='Specify Base branch identifier')
        parser.add_argument('--user', help='Specify default user for download')
        parser.add_argument('--password', help='Specify default password for download')

        self.args = parser.parse_args()
        logger.setLevel(self.args.loglevel)

        if not os.path.exists(self.args.tarball) or not os.path.isfile(self.args.tarball):
            logger.error("Input tarball %s not exist or not a file" % self.args.tarball)
            sys.exit(1)

        if self.args.apply_path:
            if not os.path.exists(self.args.apply_path):
                try:
                   os.makedirs(self.args.apply_path, mode=0o755)
                except (OSError, PermissionError) as e:
                    logger.error("Failed to create apply path: %s" % str(e))
                    sys.exit(1)
            elif not os.path.isdir(self.args.apply_path):
                logger.error("Input apply path exist, but not a folder")
                sys.exit(1)

        self.tarball =  os.path.abspath(self.args.tarball)
        self.apply_path = os.path.abspath(self.args.apply_path)
        self.env = os.environ.copy()
        self.askpass = False

        self.setup = {}
        self.extracted_folder = ""
        self.target = "N/A"

    def update_setup_config(self):
        if self.args.base_url:
            self.setup['url'] = self.args.base_url

        if self.args.base_branch:
            self.setup['branch'] = self.args.base_branch

        new_cmd = remove_user_password(self.setup['command'])
        if self.args.user and self.args.password:
            new_cmd = new_cmd + " --user=%s" % self.args.user + " --password=%s" % self.args.password

        self.setup['command'] = new_cmd

    def extract_tarball(self):
        ret = subprocess.run(['tar', '-t', '-f', self.tarball], cwd=self.apply_path, check=True, capture_output=True, text=True)
        self.extracted_folder = ret.stdout.splitlines()[0].split('/')[0].strip()

        if os.path.exists(os.path.join(self.apply_path, self.extracted_folder)):
            logger.warning("%s exist, removing it" % self.extracted_folder)
            shutil.rmtree(os.path.join(self.apply_path, self.extracted_folder))

        try:
            subprocess.run(['tar', '-x', '-f', self.tarball], cwd=self.apply_path, check=True)
        except Exception as e:
            logger.error("Failed to extract projectinfo tarball: %s" % str(e))
            sys.exit(1)

        summary_file = os.path.join(self.apply_path, self.extracted_folder, 'collection-summary.json')
        if os.path.exists(summary_file):
            with open(summary_file, "r") as f:
                json_data = json.load(f)
                self.setup = json_data['setup']
                logger.debug("Setup info: %s" % self.setup)
        else:
            logger.error("Summary file: %s not exist" % summary_file)
            sys.exit(1)

        self.target = json_data['target']

    def setup_askpass(self):
        try:
            windshare_scheme = urlparse(self.setup['url']).scheme.strip()
            if windshare_scheme not in ["http", "https", "ssh"]:
                return 0

            if not self.args.user or not self.args.password:
                return 0
            logger.info("Setting up askpass")
            askpass_script_path = os.path.join(os.path.dirname(__file__), 'wrl_askpass.sh')
            result = subprocess.run([askpass_script_path, 'start', '-u', self.setup['url'], '-d', self.apply_path,
                           '-U', self.args.user, '-P', self.args.password], check=True)
            askpass_env = os.path.join(self.apply_path, '.askpass_env')
            with open(askpass_env, "r") as f:
                lines = f.readlines()
                for line in lines:
                    envlist = line.strip().split("=")
                    self.env[envlist[0]] = envlist[1]

            self.askpass = True

        except Exception as e:
            logger.warning("Failed to setup askpass: %s" % str(e))
            self.askpass = False

    def shutdown_askpass(self):
        try:
            if self.askpass == False:
                return 0
            logger.info("Shutdowning askpass")
            askpass_script_path = os.path.join(os.path.dirname(__file__), 'wrl_askpass.sh')
            subprocess.run([askpass_script_path, 'stop', '-d', self.apply_path], check=True)
            self.askpass = False
        except Exception as e:
            logger.warning("Failed to stutdown askpass: %s" % str(e))

    def clone_wrlinux_x(self):
        try:
           logger.info("Cloning wrlinux-x")
           if self.setup['clean-repo'] == "False":
              logger.warning("Original wrlinux-x is not a clean repo, those changes will not be included in this setup")

           if self.setup['remote-commit'] != self.setup['top-commit']:
              target_topcomit = self.setup['remote-commit']
              logger.warning("Original wrlinux-x has local commits, which will not be included in this setup")
           else:
              target_topcomit = self.setup['top-commit']

           wrlinux_x_path = os.path.join(self.apply_path, 'wrlinux-x')
           if os.path.exists(wrlinux_x_path):
               logger.warning("wrlinux-x exists, removing it")
               shutil.rmtree(wrlinux_x_path)

           clone_cmd = 'git clone --branch=%s %s' % (self.setup['branch'], self.setup['url'])
           logger.info("Running: %s" % clone_cmd)
           subprocess.run(shlex.split(clone_cmd), env=self.env, cwd=self.apply_path, check=True)
           ret = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=wrlinux_x_path, check=True, capture_output=True, text=True)
           topcommit = ret.stdout

           if topcommit != target_topcomit:
               subprocess.run(['git', 'reset', '--hard', target_topcomit], cwd=wrlinux_x_path, check=True)

        except Exception as e:
            logger.error("Failed to setup project: %s" % str(e))
            raise

    def setup_project(self):
        try:
           logger.info("Setting up project")
           setup_cmd = './wrlinux-x/setup.sh ' + self.setup['command']
           logger.info("Running: %s" % setup_cmd)
           subprocess.run(shlex.split(setup_cmd + ' --accept-eula=yes'), cwd=self.apply_path, check=True)

           subprocess.run(shlex.split('bash -c ". %s"' % os.path.join(self.apply_path, 'oe-init-build-env')), cwd=self.apply_path, check=True)
           conf_dir = os.path.join(self.apply_path, 'build/conf')

           os.rename(os.path.join(conf_dir, 'local.conf'), os.path.join(conf_dir, 'local.conf.default'))
           os.rename(os.path.join(conf_dir, 'bblayers.conf'), os.path.join(conf_dir, 'bblayers.conf.default'))

           shutil.copytree(os.path.join(self.apply_path, self.extracted_folder, 'conf'), conf_dir, dirs_exist_ok=True)

           for file in os.listdir(conf_dir):
               correct_project_path(os.path.join(conf_dir, file), self.apply_path)

        except Exception as e:
            logger.error("Failed to setup project: %s" % str(e))
            raise

    def build_target(self):
        if self.target != 'N/A':
            logger.info("Running: bitbake %s" % self.target)
            try:
                buildtools = os.path.join(self.apply_path, 'environment-setup-x86_64-wrlinuxsdk-linux')
                oe_init = os.path.join(self.apply_path, 'oe-init-build-env')
                if not os.path.exists(buildtools) or not os.path.exists(oe_init):
                    logger.error("Failed to find environment-setup-x86_64-wrlinuxsdk-linux or oe-init-build-env")
                    sys.exit(1)
                returncode = None
                process = subprocess.Popen('bash -c ". %s; . %s; bitbake %s"' % (buildtools, oe_init, self.target), shell=True, cwd=self.apply_path, preexec_fn=os.setsid)
                returncode = process.wait()
            except KeyboardInterrupt:
                import signal
                os.killpg(os.getpgid(process.pid), signal.SIGINT)
                returncode = process.wait()
                raise
            except Exception as e:
                logger.error("Failed to build %s: %s" % (self.target, str(e)))
                raise
            else:
                if returncode is None or returncode != 0:
                    logger.warning("Failed to build %s, the failure may related to customer specific configuration, please check and correct" % self.target)
        else:
            logger.info("No building since target not configured")

def main():
    try:
        ret = 0
        applyer = ApplyProjectinfo()
        logger.info("Applying projectinfo tarball")
        applyer.extract_tarball()
        applyer.update_setup_config()
        applyer.setup_askpass()
        applyer.clone_wrlinux_x()
        applyer.shutdown_askpass()
        applyer.setup_project()
        applyer.build_target()
        logger.info("Applying Done")
    except KeyboardInterrupt:
        logger.error("Operation cancelled by user")
        applyer.shutdown_askpass()
        ret = 130
    except Exception as e:
        logger.error("Unexpected error: %s" % str(e))
        applyer.shutdown_askpass()
        import traceback
        traceback.print_exc()
        ret = 1
    return ret

if __name__ == "__main__":
    logger = logger_setup.setup_logging()
    ret = main()
    sys.exit(ret)
