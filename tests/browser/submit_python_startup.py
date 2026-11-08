"""Inject only the HTTP boundary for real installed CLI processes in the test VM."""
import atexit
import importlib.util
import os

if os.environ.get('QOJ_SUBMIT_FIXTURE_ROOT'):
    spec = importlib.util.spec_from_file_location(
        'submit_http_fixture', os.environ['QOJ_SUBMIT_FIXTURE_ROOT'] + '/tests/submit_http_fixture.py')
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    context = fixture.http_fixture(os.environ['QOJ_SUBMIT_FIXTURE_REPORT'], 'list-redirect')
    context.__enter__()
    atexit.register(context.__exit__, None, None, None)
    os.environ['QOJ_SUBMIT_FIXTURE_ACTIVE'] = '1'
