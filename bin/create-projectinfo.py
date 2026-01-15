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
import shutil
import subprocess
import shlex
import re
import glob
import json
import logger_setup

def get_project():
    runqemu_path = shutil.which("runqemu")
    if not runqemu_path:
        raise Exception("runqemu command not found")

    runqemu_dir = os.path.realpath(runqemu_path)
    project_topdir = os.path.normpath(os.path.join(runqemu_dir, "../../../../"))

    if not os.path.isdir(project_topdir):
        raise Exception("Project directory not found: %s" % project_topdir)

    return project_topdir

def get_today():
    return time.strftime("%Y%m%d%H%M%S")

def get_bitbake_var(var, recipe=None):
    cmd = ['bitbake-getvar']
    if recipe:
        cmd.extend(['-r', recipe])
    cmd.append(var)

    ret=subprocess.run(cmd, check=True, capture_output=True, text=True)
    for line in ret.stdout.split('\n'):
        if line.startswith(f'{var}='):
            return line.split('=', 1)[1].strip('"')
    return None

def remove_all_functions(file):
    pattern = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)(?::[A-Za-z_][A-Za-z0-9_]*)?\s*\(\s*\)\s*\{')

    remove_index = None
    with open(file, 'r') as f:
        lines = f.readlines()

    for i, line in enumerate(lines):
        if pattern.match(line):
            remove_index =  i - 1
            break

    if line is not None:
        new_lines = lines[:remove_index]
        with open(file, 'w') as f:
            f.writelines(new_lines)

class CreateProjectinfo(object):
    """
    * Create project info tarball, may include:
        - setup log
        - all configuration files under conf
        - bitbake info
        - kernel config
        - image manifest files
    """

    def __init__(self):
        parser = argparse.ArgumentParser(description="create-projectinfo.py: Application to create a tarball that includes project info")
        parser.add_argument("-d", "--debug", help = "Enable debug output",
            action="store_const", const=logging.DEBUG, dest="loglevel", default=logging.INFO)
        parser.add_argument('-p', '--project', default = '', help='Specify project name')
        parser.add_argument('-t', '--target', default = '', help='Specify target name, used by bitbake -e and bitbake -g')
        self.args = parser.parse_args()
        logger.setLevel(self.args.loglevel)

        self.bitbake_path = shutil.which('bitbake')
        self.builddir = os.getenv('BUILDDIR')
        if not (self.bitbake_path and self.builddir):
            raise Exception('bitbake command is not found, this tools should be run after source oe-init-build-env')

        self.today = get_today()
        self.project_topdir = get_project()
        self.wrlinux_version = get_bitbake_var('WRLINUX_VERSION')
        self.projectinfo_dir = os.path.join(self.project_topdir, 'config/projectinfo/WRLinux' + '-' + self.wrlinux_version + '-' + self.today)

        if not os.path.exists(self.projectinfo_dir):
            os.makedirs(self.projectinfo_dir, mode=0o755)

    def remove_sensitive_info(self, file, project_path = True, functions = False, wrlinux_x_path = False, username = False, hostname = False):
        if project_path:
            subprocess.run(['sed', '-i', '-e', 's#%s#/PROJECT_TOPDIR#g' % self.project_topdir, file], check=True)

        if functions:
            remove_all_functions(file)

        if wrlinux_x_path:
            subprocess.run(['sed', '-i', '-e', 's#.*wrlinux-x/EULA.*#/WRLINUX-X_TOPDIR/wrlinux-x/EULA#g', file], check=True)

        if username:
            ret=subprocess.run(['whoami'], check=True, capture_output=True, text=True)
            uname = ret.stdout.strip()
            subprocess.run(['sed', '-i', '-e', 's#%s#WHOAMI#g' % uname, file], check=True)

        if hostname:
            ret=subprocess.run(['hostname'], check=True, capture_output=True, text=True)
            hname = ret.stdout.strip()
            subprocess.run(['sed', '-i', '-e', 's#%s#HOSTNAME#g' % hname, file], check=True)

    def collect_setup_log(self):
        logger.info("Collecting latest setup log under %s/config/log" % self.project_topdir)
        latest_setup_log = os.path.join(self.project_topdir, 'config/log/setup-latest.log')
        if os.path.exists(latest_setup_log):
            try:
                setup_log = os.path.join(self.projectinfo_dir, 'setup.log')
                shutil.copy(latest_setup_log, setup_log)
            except (OSError, PermissionError) as e:
                logger.error("Failed to collect setup log: %s" % str(e))
                sys.exit(1)

            self.remove_sensitive_info(setup_log, wrlinux_x_path=True, username=True, hostname=True)
        else:
            logger.error("Failed to collect setup log: not found under %s" % os.path.join(self.project_topdir, 'config/log'))
            sys.exit(1)

    def collect_configuration(self):
        logger.info("Collecting all configuration files under %s/conf" % self.builddir)
        conf_src = os.path.join(self.builddir, 'conf')
        conf_dst = os.path.join(self.projectinfo_dir, 'conf')

        if os.path.exists(conf_src):
            try:
                shutil.copytree(conf_src, conf_dst)
            except (OSError, PermissionError) as e:
                logger.error("Failed to collect configuration: %s" % str(e))
                sys.exit(1)

            for file in os.listdir(conf_dst):
                self.remove_sensitive_info(os.path.join(conf_dst, file))
        else:
            logger.error("Failed to collect configuration: not found under %s" % conf_src)
            sys.exit(1)

    def collect_bitbake_info(self):
        logger.info("Collecting global bitbake enviroment generated by bitbake -e")
        try:
            env_file = os.path.join(self.projectinfo_dir, 'bitbake-global.env')
            with open(env_file, 'w') as f:
                subprocess.run(['bitbake', '-e'], stdout=f, stderr=subprocess.STDOUT, check=True)
        except Exception as e:
            logger.warning("Failed to collect bitbake global environment: %s" % str(e))

        self.remove_sensitive_info(env_file, functions=True)

        if self.args.target:
            if not re.match(r'^[a-zA-Z0-9_.-]+$', self.args.target):
                raise ValueError("Invalid target name: %s" % self.args.target)

            try:
                logger.info("Collecting target bitbake enviroment generated by bitbake -e %s" % self.args.target) 
                target_env_file = os.path.join(self.projectinfo_dir, 'bitbake-' + self.args.target + '.env')
                with open(target_env_file, 'w') as f:
                    subprocess.run(['bitbake', self.args.target, '-e'], stdout=f, stderr=subprocess.STDOUT, check=True)
            except Exception as e:
                logger.warning("Failed to collect bitbake per-recipe enviroment info for %s: %s" % (self.args.target, str(e)))

            self.remove_sensitive_info(target_env_file, functions=True)

            try:
                logger.info("Collecting target dependency tree information generated by bitbake %s -g" % self.args.target)
                subprocess.run(['bitbake', self.args.target, '-g'], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, check=True)
                for graph_file in ['task-depends.dot', 'pn-buildlist']:
                    src_path = os.path.join(self.builddir, graph_file)
                    if os.path.exists(src_path):
                        shutil.copy2(src_path, os.path.join(self.projectinfo_dir, self.args.target + '-' + graph_file))
            except Exception as e:
                logger.warning("Failed to collect dependency tree information for %s: %s" % (self.args.target, str(e)))

            self.remove_sensitive_info(os.path.join(self.projectinfo_dir, self.args.target + '-' + 'task-depends.dot'))

    def collect_kernel_config(self):
        logger.info("Collecting kernel configuration")
        try:
            kernel_B = get_bitbake_var('B', 'virtual/kernel')
            if not kernel_B:
                logger.warning("Could not determine kernel build directory")
                return

            kernel_config = os.path.join(kernel_B, '.config')
            if os.path.exists(kernel_config):
                try:
                    shutil.copy(kernel_config, os.path.join(self.projectinfo_dir, 'kernel.config'))
                except (OSError, PermissionError) as e:
                    logger.warning("Failed to collect kernel config: %s" % str(e))
            else:
                 logger.warning("Failed to collect kernel config: not found under %s" % kernel_B)
        except Exception as e:
            logger.warning("Failed to collect kernel config: %s" % str(e))

    def collect_manifest_files(self):
        try:
            deploy_image_dir = get_bitbake_var('DEPLOY_DIR_IMAGE')
            logger.info("Collecting all manifest files under %s" % deploy_image_dir)
            notfound = True
            for manifest_file in glob.glob(os.path.join(deploy_image_dir, '*.manifest')):
                if not os.path.islink(manifest_file):
                    shutil.copy(manifest_file, self.projectinfo_dir)
                    notfound = False
            if notfound:
                logger.warning("Failed to collect manifest files: not found under %s" % deploy_image_dir)
        except Exception as e:
            logger.warning("Failed to collect manifest files: %s" % str(e))

    def create_projectinfo_tarball(self):
        logger.info("Collecting project information")

        self.collect_setup_log()
        self.collect_configuration()
        self.collect_bitbake_info()
        self.collect_kernel_config()
        self.collect_manifest_files()

        # Create summary file
        summary_file = os.path.join(self.projectinfo_dir, 'collection-summary.json')
        json_data = {
            'collection-time': time.strftime("%Y-%m-%d %H:%M:%S"),
            'wrlinux-version': self.wrlinux_version,
            'project': self.args.project or 'N/A',
            'target': self.args.target or 'N/A'
        }

        files_list = []
        for root, dirs, files in os.walk(self.projectinfo_dir):
            for file in files:
                rel_path = os.path.relpath(os.path.join(root, file), self.projectinfo_dir)
                files_list.append(rel_path)
        json_data['files-list'] = files_list

        if os.path.exists(os.path.join(self.projectinfo_dir, 'setup.log')):
            json_data['setup'] = {}
            with open(os.path.join(self.projectinfo_dir, 'setup.log'), 'r') as f:
                for line in f:
                    match_command = re.match(r'Setup Command: (.+)', line)
                    match_url = re.match(r'Remote URL of wrlinux-x: (.+)', line)
                    match_branch = re.match(r'Basebranch of wrlinux-x: (.+)', line)
                    match_topcommit = re.match(r'Top Commit: (.+)', line)
                    match_remote_topcommit = re.match(r'.*top commit of remote origin HEAD: (.+)', line)
                    match_unclean_repo = re.match(r'WARNING: wrlinux-x is not a clean repo.', line)
                    if match_command:
                        json_data['setup']['command'] = match_command.group(1).strip()
                    if match_url:
                        json_data['setup']['url'] = match_url.group(1).strip()
                    if match_branch:
                        json_data['setup']['branch'] = match_branch.group(1).strip()
                    if match_topcommit:
                        json_data['setup']['top-commit'] = match_topcommit.group(1).strip()
                    if match_remote_topcommit:
                        json_data['setup']['remote-commit'] = match_remote_topcommit.group(1).strip()
                    if match_unclean_repo:
                        json_data['setup']['clean-repo'] = 'False'

            if 'remote-commit' not in json_data['setup']:
               json_data['setup']['remote-commit'] = json_data['setup']['top-commit']
            if 'clean-repo' not in json_data['setup']:
                json_data['setup']['clean-repo'] = 'True'

        with open(summary_file, "w") as f:
            json.dump(json_data, f, indent=4)

        # Create tarball safely
        tarball_name = os.path.basename(self.projectinfo_dir) + '.tar.xz'
        dir_name = os.path.basename(self.projectinfo_dir)
        parent_dir = os.path.dirname(self.projectinfo_dir)

        logger.info("Creating tarball")
        subprocess.run(['tar', '-cJf', tarball_name, dir_name], cwd=parent_dir, check=True)

        # Validate path before removal
        if os.path.exists(self.projectinfo_dir) and self.projectinfo_dir.startswith(self.project_topdir):
            shutil.rmtree(self.projectinfo_dir)

        tarball_path = os.path.join(parent_dir, tarball_name)
        tarball_size = os.path.getsize(tarball_path) / (1024 * 1024)  # MB
        logger.info("Project info tarball created: %s (%.1f MB)" % (tarball_path, tarball_size))
        logger.warning(f'''
    The {tarball_name} may contain the following sensitive info:
    * Your local recipe name
    * Your local layer name
    * Maybe other sensitive info
    Please make sure no confidential information is part of the tarball before sharing with Wind River.''')

def main():
     creator = CreateProjectinfo()
     creator.create_projectinfo_tarball() 
     return 0

if __name__ == "__main__":
    try:
        logger = logger_setup.setup_logging()
        ret = main()
    except KeyboardInterrupt:
        logger.error("Operation cancelled by user")
        ret = 130
    except Exception as e:
        logger.error("Unexpected error: %s" % str(e))
        import traceback
        traceback.print_exc()
        ret = 1
    sys.exit(ret)
