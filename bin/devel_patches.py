#!/usr/bin/env python3

# Copyright (C) 2026 Wind River Systems, Inc.
#
import sys
import subprocess
import glob
import os
import argparse
import logging
import shutil
import tarfile
import urllib.request
import urllib.error

import logger_setup

logger = logger_setup.setup_logging()

class DevPatches(object):
    def __init__(self):
        parser = argparse.ArgumentParser(
            description="Apply hotfix patches.",
            epilog="Use %(prog)s --help to get help")
        parser.add_argument("-u", "--url", help="Specify the url to dowload")
        parser.add_argument("-p", "--project", help="Specify the project dir", default=os.getcwd())
        parser.add_argument("-o", "--outdir", help="Specify the output dir", default=os.getcwd())
        parser.add_argument("-d", "--debug",
            help = "Enable debug output",
            action="store_const", const=logging.DEBUG, dest="loglevel", default=logging.INFO)
        parser.add_argument("-q", "--quiet",
            help = "Hide all output except error messages",
            action="store_const", const=logging.ERROR, dest="loglevel")

        self.args = parser.parse_args()

        self.project = self.args.project

        if not self.project:
            self.project = os.get.cwd()

        self.layers = os.path.join(self.project, 'layers')
        logger.info("Layers dir: %s" % self.layers)

        self.url = self.args.url
        self.outdir = self.args.outdir
        self.filename = os.path.basename(self.url)[:-7]

        if not os.path.exists(self.layers):
            raise Exception('Failed to find %s' % self.layers)

    def find_repo(self, dn):
        full_path_p = os.path.join(self.project, dn)
        bn = os.path.basename(full_path_p)
        dn_2 = os.path.dirname(full_path_p)
        new_path = full_path_p
        if '-dl-' in bn:
            bn_new = '-'.join(bn.split('-')[:-1])
            new_path = os.path.join(dn_2, bn_new)

        if not os.path.exists(new_path):
            logger.warning('Failed to find %s' % new_path)
            return ''

        # Check whether the repos are matched or not
        if new_path.endswith('/wrlinux-x'):
            cmd = 'git config --get remote.origin.url'
        else:
            cmd = 'git config --get remote.base.url'

        url = subprocess.check_output(cmd, shell=True, cwd=new_path).decode('utf-8').strip()
        url_bn = os.path.basename(url)

        if url_bn != bn:
            logger.warning("The layer doesn't match: '%s' vs '%s'" % (bn, url_bn))
            return ''

        return new_path

    def create_branch(self, new_path):
        cmd = 'git branch -f %s HEAD' % self.filename
        subprocess.check_output(cmd, shell=True, cwd=new_path)

    def apply_patches(self):
        path = os.path.join(self.outdir, self.filename)
        handled = set()
        for root, dirs, files in os.walk(path):
            for file in files:
                full_path = os.path.join(root, file)
                short_path = full_path[len(path)+1:]
                dn = os.path.dirname(short_path)
                new_path = self.find_repo(dn)
                if new_path and not new_path in handled:
                    handled.add(new_path)
                    logger.info('Applying patches in %s' % new_path)
                    patches = '%s/*.patch' % os.path.dirname(full_path)
                    cmd = 'git am -q --whitespace=nowarn %s ' % patches
                    url = subprocess.check_output(cmd, shell=True, cwd=new_path)
                    self.create_branch(new_path)
        logger.info("All patches are applied successfully")

    def download_and_extract(self):
        if self.url.startswith(('http://', 'https://')):
            logger.info(f"Downloading from {self.url}...")
            filename_tar = self.filename + '.tar.xz'
            try:
                urllib.request.urlretrieve(self.url, filename_tar)
                path = filename_tar
            except urllib.error.HTTPError as e:
                # Handle HTTP errors (e.g., 403, 404, 500)
                logger.error(f"HTTP Error: {e.code} - {e.reason}")
                sys.exit(1)

            except urllib.error.URLError as e:
                # Handle URL errors (e.g., connection refused, DNS failure)
                logger.error(f"URL Error: {e.reason}")
                sys.exit(1)

            except Exception as e:
                # Handle any other unexpected errors
                logger.errror(f"An unexpected error occurred: {e}")
                sys.exit(1)
        else:
            path = self.url

        if os.path.exists(path) and (path.endswith('.tar.xz') or path.endswith('.tar.gz')):
            logger.info(f"Extracting {path} to {self.outdir}...")
            cmd = "XZ_OPT='-T0' tar -xf %s -C %s" % (path, self.outdir)
            subprocess.check_output(cmd, shell=True)
        else:
            logger.error(f"File '{path}' not found or unsupported format.")
            sys.exit(1)

def main():
    dev_patches = DevPatches()
    dev_patches.download_and_extract()
    dev_patches.apply_patches()

if __name__ == "__main__":
    try:
        ret = main()
    except Exception as esc:
        ret = 1
        import traceback
        traceback.print_exc()
    sys.exit(ret)
