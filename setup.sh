#!/bin/bash
#
# Copyright (C) 2016 Wind River Systems, Inc.
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

if [ -z "${BASH_VERSION}" ]; then
	echo "This script must be run with bash." >&2
	exit 1
fi

which python3 > /dev/null
if [ $? -ne 0 ]; then
       echo >&2 "WRLinux setup requires 'python3'."
       echo >&2 "Please install python3."
       exit 1
fi

if [ `id -u` = 0 ]; then
       echo >&2 "Do not run setup as root."
       exit 1
fi

: "${GIT_USERNAME=customer}"
: "${GIT_USEREMAIL=customer@company.com}"

# Requires python3
CMD="bin/setup.py"

# Adds arguments to the arg processing
#   1 - argument
#   2 - variable to define
#   3 - keep or discard (if defined, keep)
#       there may be arguments you don't want passed to the .py script
setup_add_arg() {
	found=0
	for parse in ${ARGPARSE[@]}; do
		comp=${parse%%:*}
		if [ "${comp}" = "$1" ]; then
			found=1
		fi
	done

	if [ ${found} -eq 0 ]; then
		ARGPARSE[${#ARGPARSE[@]}]="$1:$2:$3"
	fi
}

# Functions that add functionality during early processing
setup_add_func() {
	ADDFUNCS[${#ADDFUNCS[@]}]="$1"
}

# Functions that export variables (or need to run very late)
setup_export_func() {
	EXPORTFUNCS[${#EXPORTFUNCS[@]}]="$1"
}

# Functions that run on shutdown
setup_shutdown_func() {
	SHUTDOWNFUNCS[${#SHUTDOWNFUNCS[@]}]="$1"
}

# Takes value_name default_value
# value_name is set to the first value found in the list:
# git config, git config --global, and finally default_value
add_gitconfig() {
	if [ $# -eq 1 ]; then
		VAR=$(git config "$1" || git config --global "$1")
	elif [ $# -eq 2 ]; then
		VAR=$(git config "$1" || git config --global "$1" || echo "$2")
	else
		echo "ERROR: Only one or two args are supported, but got $#"
		return 1
	fi

	[ -n "${VAR}" ] && git config -f .gitconfig "${1}" "${VAR}"
}

shutdown() {
	for func in "${SHUTDOWNFUNCS[@]}"; do
		# During shutdown, we don't care about return codes
		$func
	done
}

shutdown_handler() {
    echo -e "\nAborted by user, will terminate this setup."
    shutdown
    exit 1
}

# Input: argument list
# Output: 'help=1' or unset
#          PASSARGS set to the arguments to pass on
parse_arguments() {
	local found keep comp next val
	while [ $# -ge 1 ] ; do
		found=0
		if [ "$1" = "--help" -o "$1" = "-h" ]; then
			# Default into a --help module which is part of setup.py
			help=1
			PASSARGS[${#PASSARGS[@]}]="$1"
			shift
			continue
		fi
		for parse in ${ARGPARSE[@]}; do
			comp=${parse%%:*}
			next=${parse#${comp}:}
			val=${next%%:*}
			next=${next#${val}:}
			if [ "${next}" != "${val}" ]; then
				keep=${next}
			else
				keep=""
			fi
			case "$1" in
				${comp}=*)
					eval ${val}=\${1#*=}
					if [ -n "${keep}" ]; then
						PASSARGS[${#PASSARGS[@]}]="$1"
					fi
					shift
					found=1
					break
					;;
				${comp})
					eval ${val}=\${2}
					if [ -n "${keep}" ]; then
						PASSARGS[${#PASSARGS[@]}]="$1"
						# Only check whether $2 is set or not, set to "" or '--foo'
						# should work because:
						# - set to "": keep align with argparse since it works in this way.
						# - set to "--foo": argparse knows it's not the arg of $1,
						#                   but another option, and can handle it correctly.
						if [ -n "${2+x}" ]; then
							PASSARGS[${#PASSARGS[@]}]="$2"
						fi
					fi
					if [ -z "${2+x}" ]; then
						shift 1
					else
						shift 2
					fi
					found=1
					break
					;;
			esac
		done
		if [ $found -ne 1 ]; then
			PASSARGS[${#PASSARGS[@]}]="$1"
			shift
		fi
	done
}

check_if_safe_directory_set() {
	if [ "^*$" == "$1" ]; then
		if git config --get-all safe.directory | grep "^*$" 2>&1 >/dev/null; then
			return 0
		fi
	else
		set -f
		for path in $(git config --get-all safe.directory | grep "*$"); do
			safe_dir=$(realpath $(dirname $path))
			if [ "$safe_dir" == "$1" ]; then
				return 0
			fi
		done
		set +f
	fi
	return 1
}

calculate_setup_time() {
	start_time=$1
	end_time=$2
	runtime=$((end_time - start_time))
	hours=$((runtime / 3600))
	minutes=$(( (runtime % 3600) / 60 ))
	seconds=$((runtime % 60))
	echo $hours"h"$minutes"m"$seconds"s"
}

write_metrics_into_log() {
	setupcommand=$1
	setuptime=$2
	osinfo=$(cat /etc/os-release)
	archinfo=$(uname -m)
cat <<EOF >> $LOGFILE

========== Metric Info ==========
Setup Command: $setupcommand
Remote URL of wrlinux-x: $REMOTEURL
Basebranch of wrlinux-x: $BASEBRANCH
Setup Time: $setuptime
OS Info:
$osinfo
Arch Info: $archinfo
EOF
}

generate_tmp_log() {
	tmpfile=$(mktemp)
	line1="Subject: WRLinux Setup Failure Log"
	line2=""
	cp $LOGFILE $tmpfile
	#Insert Subject: line to pass the subject line check of git-send-email
	sed -i "1i $line1\n$line2" $tmpfile
	 #Remove possible sensitive info in the log
	sed -i -e "s#$BASEDIR#PATH_OF_WRLINUX-X#g" $tmpfile
	sed -i -e "s#$PWD#/PATH_OF_PROJECT_DIR#g" $tmpfile
	sed -i -e "s#$(whoami)#WHOAMI#g" $tmpfile
	sed -i -e "s#$(hostname)#HOSTNAME#g" $tmpfile
	echo $tmpfile
}

send_log() {
	tmplog=$(generate_tmp_log)

	if [ -n "${INTERNEL_TEST_LOGMAIL}" ]; then
		LOGMAIL="${INTERNEL_TEST_LOGMAIL}"
	fi

	if [ -z "${LOGMAIL}" ]; then
		LOGMAIL="WRL-build-feedback@windriver.com"
	fi

	if ! git send-email --to $LOGMAIL $tmplog; then
		echo "WARNING: Send setup log to windriver failed, please ensure git-email is installed and has correct configuration" >&2
		echo "WARNING: Refer: https://git-scm.com/docs/git-send-email" >&2
	fi
	rm -rf $tmplog
}

check_if_need_to_send_log() {
	sendlog="0"
	for arg in $SETUPCMD ; do
		if [ "$arg" = "--send-log" ]; then
			sendlog="1"
			break
		fi
	done
	if [[ "$sendlog" -eq "0" ]]; then
		return 1
	fi
	retcode=$1
	# setup success, don't send log
	if [[ "$retcode" -eq "0" ]]; then
		return 1
	fi
	# SIGINT received, don't send log
	if [[ "$retcode" -eq "130"  || "$retcode" -eq "99" ]]; then
		return 1
	fi
	# if invalue argument is passed, don't send log
	if grep -q "unrecognized arguments:" $LOGFILE; then
		return 1
	fi
	return 0
}

create_log_file() {
	logdir="$PWD/config/log"
	mkdir -p "$logdir"
	logfile=$(date +%Y%m%d%H%M%S).log
	touch "$logdir"/"$logfile"
	cd "$logdir" && ln -sf "$logfile" setup-latest.log && cd - 1>/dev/null || exit 1
	echo "$logdir/$logfile"
}

LOGFILE=$(create_log_file)
STARTTIME=$(date +%s)
ENDTIME=
SETUPCMD="$@"

trap shutdown_handler INT

# Setup the minimal defaults first..
# BASEDIR, BASEURL and BASEBRANCH
BASEDIR=$(readlink -f "$(dirname "$0")")

# Argument parsing, define a limited set of args
setup_add_arg --base-url BASEURL keep
setup_add_arg --base-branch BASEBRANCH keep
setup_add_arg --log-mail LOGMAIL keep

help=0
parse_arguments "$@"
unset PASSARGS

# setup git url
REMOTEURL=$(cd "$BASEDIR" ; git config remote.origin.url 2>/dev/null)

# BASEURL is one directory above the git checkout
BASEREPO=""
if [ -z "${BASEURL}" ]; then
	BASEURL=$(echo "$REMOTEURL" | sed -e 's,/$,,' -e 's,/[^/]*$,,')
	BASEREPO=${REMOTEURL##$BASEURL\/}
fi

# First check if this is an absolute path (starts w/ '/')
# If it's not, we then check if it's a valid URL (contains ://)
if [ "${BASEURL:0:1}" != '/' ]; then
	if [ "${BASEURL#*://}" == "${BASEURL}" -a "${BASEURL#*:}" == "${BASEURL}" ]; then
		echo >&2
		echo "ERROR: The BASEURL ($BASEURL) is not in a supported format." >&2
		if [ -n "${BASEREPO}" ]; then
			echo "The BASEURL was derived from the URL of $BASEREPO ($REMOTEURL)." >&2
			echo "Either update the repository URL or use the --base-url argument to override." >&2
		fi
		echo >&2
		echo "BASEURL must use an absolute file path, or a properly formatted remote URL" >&2
		echo "such as:" >&2
		echo "  /home/user/path or file:///home/user/path" >&2
		echo "  http://hostname/path" >&2
		echo "  https://hostname/path" >&2
		echo "  git://hostname/path" >&2
		echo "  ssh://user@hostname/path" >&2
		echo "  [user@]hostname:path" >&2
		echo >&2
		exit 1
	fi
fi

git_cmd="git --git-dir=$BASEDIR/.git"
if [ -z "${BASEBRANCH}" ]; then
	BASEBRANCH=$($git_cmd rev-parse --abbrev-ref HEAD)
	if [ "$BASEBRANCH" = "HEAD" ]; then
		# Maybe this is a tag instead?
		BASEBRANCH=$($git_cmd describe HEAD 2>/dev/null)
		if [ $? -ne 0 ]; then
			# No reasonable branch/tag name found...
			BASEBRANCH=""
		else
			echo "$BASEBRANCH" | grep -q "vWRLINUX_CI_"
			if [ $? -ne 0 ]; then
				echo "ERROR: Tag $BASEBRANCH is not supported by setup.sh, please use a branch." >&2
				echo ""
				exit 1
			fi
			latest_tag=$($git_cmd tag --sort=taggerdate |tail -1)
			if [ "$latest_tag" != "$BASEBRANCH" ]; then
					echo "ERROR: Only latest tag is supported" >&2
					echo "ERROR: Current tag: $BASEBRANCH" >&2
					echo "ERROR: Latest  tag: $latest_tag" >&2
					echo ""
					exit 1
			fi
			BASEBRANCH="refs/tags/$BASEBRANCH"
		fi
	fi
fi

# Load custom setup additions
if [ -d "${BASEDIR}/data/environment.d" ]; then
	for envfile in ${BASEDIR}/data/environment.d/*.sh ; do
		. $envfile
	done
fi

# We need to reparse the arguments as we've now loaded the environment.d
# extensions
help=0
parse_arguments "$@"

if [ $help -ne 1 ]; then
	# Before doing anything else, error out if the project directory
	# is unsafe.
	case "$PWD" in
		$BASEDIR | $BASEDIR/*)
		echo >&2 "$0: The current working directory is used as your project directory"
		echo >&2 "    Your project directory must not be in or under"
		echo >&2 "    '${BASEDIR}'"
		echo >&2 ""
		echo >&2 "    Typically a project is setup by doing:"
		echo >&2 "      $ mkdir my_project"
		echo >&2 "      $ cd my_project"
		echo >&2 "      $ git clone --branch $BASEBRANCH $REMOTEURL"
		echo >&2 "      $ .$(echo $REMOTEURL | sed "s,$BASEURL,,")/setup.sh $@"
		exit 1
		;;
	esac

	if [ -z "$BASEBRANCH" ]; then
		echo "May be on a detached HEAD, HEAD must be on a branch or tag. ($BASEDIR)" >&2
		echo "You can avoid this by passing the branch using --base-branch=" >&2
		exit 1
	fi

        # Is this a tag?  If so, don't allow tags w/ '-'
	if [ "$BASEBRANCH" != "${BASEBRANCH##refs/tags/}" ]; then
		if [ "$BASEBRANCH" != "${BASEBRANCH//-*}" ]; then
			echo "Checkout may be on a detached HEAD, this HEAD does not appear to" >&2
			echo "correspond to a specific, tag.  (It appears you may be working with" >&2
			echo "tag ${BASEBRANCH//-*}.  If this is correct, use" >&2
			echo "--base-branch=${BASEBRANCH//-*} in the arguments to" >&2
			echo "$0."
			exit 1
		fi
	fi

	if ([[ "$REMOTEURL" = /* ]] || [[ "$REMOTEURL" = "file://"* ]]); then
		remote_url=$REMOTEURL
		if [[ "$remote_url" = "file://"* ]]; then
			remote_url=${remote_url:7}
		fi
		current_user_euid=$(id -u)
		remoteurl_owner_euid=$(stat -c %u $remote_url)
		if [ "$current_user_euid" != "$remoteurl_owner_euid" ]; then
			host_git_ver=$(git version | awk '{printf $3}')
			required_git_ver=2.46.0
			safe_dir=$(realpath $(dirname $remote_url))

			if [ ! "$(printf '%s\n' "$required_git_ver" "$host_git_ver" | sort -V | head -n1)" = "$required_git_ver" ]; then
				if !(check_if_safe_directory_set "^*$"); then
					echo "ERROR: git cannot access directories owned by someone other than the current." >&2
					echo "ERROR: You need run the following command to avoid setup failures:" >&2
					echo "ERROR: $ git config --global --add safe.directory \"*\"" >&2
					echo "ERROR: Refer: https://github.com/git/git/commit/f4aa8c8bb11dae6e769cd930565173808cbb69c8" >&2
					echo "ERROR: If you prefer to set like following command, you need to upgrade host git to 2.46.0+" >&2
					echo "ERROR: $ git config --global --add safe.directory \"$safe_dir/*\"" >&2
					echo "ERROR: Refer: https://github.com/git/git/commit/313eec177ad010048b399d6fd14de871b517f7e3" >&2
					exit 1
				fi
			else
				if !(check_if_safe_directory_set "^*$") && !(check_if_safe_directory_set "$safe_dir"); then
					echo "ERROR: git cannot access directories owned by someone other than the current." >&2
					echo "ERROR: You need run one of the following commands to avoid setup failures:" >&2
					echo "ERROR: $ git config --global --add safe.directory \"$safe_dir/*\"" >&2
					echo "ERROR: $ git config --global --add safe.directory \"*\"" >&2
					echo "ERROR: Refer: https://github.com/git/git/commit/f4aa8c8bb11dae6e769cd930565173808cbb69c8" >&2
					echo "ERROR: Refer: https://github.com/git/git/commit/313eec177ad010048b399d6fd14de871b517f7e3" >&2
					exit 1
				fi
			fi
		fi
	fi

	exec 3>&1 4>&2
	exec > >(tee -a $LOGFILE) 2>&1
	for func in "${ADDFUNCS[@]}"; do
		$func
		rc=$?
		if [ $rc -ne 0 ]; then
			echo "Stopping: an error occurred in $func." >&2
			shutdown
			exec 1>&3 2>&4
			exec 3>&- 4>&-
			ENDTIME=$(date +%s)
			setuptime=$(calculate_setup_time $STARTTIME $ENDTIME)
			write_metrics_into_log "$SETUPCMD" $setuptime
			if check_if_need_to_send_log $rc;then
				send_log
			fi
			exit $rc
		fi
	done
	exec 1>&3 2>&4
	exec 3>&- 4>&-

	# Configure the current directory so repo works seemlessly
	add_gitconfig "user.name" "${GIT_USERNAME}"
	add_gitconfig "user.email" "${GIT_USEREMAIL}"
	add_gitconfig "color.ui" "false"
	add_gitconfig "color.diff" "false"
	add_gitconfig "color.status" "false"
	add_gitconfig "http.proxyauthmethod"
	add_gitconfig "http.proxy"
	add_gitconfig "safe.directory"
fi # if help -ne 1

# We potentially have code that doesn't parse correctly with older versions 
# of Python, and rather than fixing that and being eternally vigilant for 
# any other new feature use, just check the version here.
py_v36_check=$(python3 -c 'import sys; print(sys.version_info >= (3,8,0))')
if [ "$py_v36_check" != "True" -a $help -ne 1 ]; then
	echo >&2 "BitBake requires Python 3.8.0 or later as 'python3'"
	exit 1
fi
unset py_v36_check

# This can happen if python3/urllib was not built with SSL support.
python3 -c 'import urllib.request ; dir(urllib.request.HTTPSHandler)' >/dev/null 2>&1
if [ $? -ne 0 ]; then
	echo >&2 "The setup tool requires Python 3.4.0 or later with support for 'urllib.request.HTTPSHandler'"
	exit 1
fi

# Correct local timezone file for logging
export TZ="/etc/localtime"

# Python 3 required utf-8 support to work properly, adjust the LANG to en_US.UTF-8.
export LANG='en_US.UTF-8'

# Pass the computed url and branch to ${cmd}
export OE_BASEURL=${BASEURL}
export OE_BASEBRANCH=${BASEBRANCH}

for func in "${EXPORTFUNCS[@]}"; do
	$func
	rc=$?
	if [ $rc -ne 0 ]; then
		echo "Stopping: an error occurred in $func." >&2
		shutdown
		exit $rc
	fi
done

trap - INT

# Switch to the python script
${BASEDIR}/${CMD} "${PASSARGS[@]}" $LOGFILE
rc=$?

shutdown

ENDTIME=$(date +%s)
setuptime=$(calculate_setup_time $STARTTIME $ENDTIME)
write_metrics_into_log "$SETUPCMD" $setuptime
if check_if_need_to_send_log $rc;then
	send_log
fi

# Preserve the return code from the python script
exit $rc
