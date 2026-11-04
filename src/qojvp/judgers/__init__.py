"""Judger interface: execute(action, args, exchange).

Actions: contest, bind_virtual, confirm_virtual_start, problem_form, samples,
prepare_resource, submit, submissions, reconcile. Provider submission IDs and
receive times are facts; an ambiguous send is never automatically retried.
"""
