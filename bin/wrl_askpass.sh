#!/bin/bash
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

# In order to reuse 03_wrl_askpass.sh, define 3 empty functions to avoid
# 'command not found' error
setup_add_arg() {
 :
}

setup_add_func() {
 :
}

setup_shutdown_func() {
 :
}

usage() {
    echo "Usage:"
    echo "  $0 start -u URL -d APPLYDIR -U USER -P PASSWORD"
    echo "  $0 stop -d APPLYDIR"
    exit 1
}

ACTION="$1"
shift || true

case "$ACTION" in
    start|stop)
        ;;
    *)
        usage
        ;;
esac

while getopts "u:d:U:P:" opt; do
    case "$opt" in
        u)
            BASEURL="$OPTARG"
            ;;
        d)
            APPLYDIR="$OPTARG"
            ;;
        U)
            WINDSHARE_USER="$OPTARG"
            ;;
        P)
            WINDSHARE_PASS="$OPTARG"
            ;;
        *)
            usage
            ;;
    esac
done

if [ "$ACTION" = "start" ]; then
   [ -z "$BASEURL" ] && usage
   [ -z "$APPLYDIR" ] && usage
   [ -z "$WINDSHARE_USER" ] && usage
   [ -z "$WINDSHARE_PASS" ] && usage
elif [ "$ACTION" = "stop" ]; then
   [ -z "$APPLYDIR" ] && usage
fi

BASEDIR=$(dirname "$0")/..
source $BASEDIR/data/environment.d/03_wrl_askpass.sh
ASKPASS_ENV_FILE=${APPLYDIR}/.askpass_env
export WRL_ASKPASS_SOCKET=${APPLYDIR}/.setup_askpass

case "$ACTION" in
    start)
       rm -rf $ASKPASS_ENV_FILE
       askpass_setup
       echo "GIT_SSH=${GIT_SSH}" > ${ASKPASS_ENV_FILE}
       echo "SSH_ASKPASS=${SSH_ASKPASS}" >> ${ASKPASS_ENV_FILE}
       echo "GIT_ASKPASS=${GIT_ASKPASS}" >> ${ASKPASS_ENV_FILE}
       echo "WRL_ASKPASS_SOCKET=${WRL_ASKPASS_SOCKET}" >> ${ASKPASS_ENV_FILE}
       exit $?
    ;;
    stop)
       askpass_shutdown
       rm -rf $ASKPASS_ENV_FILE
       exit $?
    ;;
    *) 
    usage
    ;;
esac

exit 0
