#!/bin/bash

if [[ $# -eq 0 ]] ; then
    echo 'please specify install, deploy, cron, manage, manage_tmux or tiles_install'
    exit 1
fi

source .env;

# Assigning the first argument to ansible playbook variable
ansible_playbook=$1

# Shift the arguments so the rest represent the command to be executed on the prod server
shift

# In case of manage, we store the django command in extra_vars variable
extra_vars=$(printf '{"extra_command": "%s"}' "$*")

ANSIBLE_CONFIG=ansible/ansible.cfg ansible-playbook ansible/prod/$ansible_playbook.yml -K -u ubuntu -i ansible/prod/hosts -vvv --extra-vars "$extra_vars"