#!/usr/bin/env python3
"""Check that module dependencies abide by architectural rules.

Rules:
  1. Cross-module imports are only allowed to:
     - Django models (app/models.py or app/models/*.py)
     - Public API files (app/public_workflow.py, public_service.py, public_model.py)
     - Utils (app/utils/*.py)
     - Any file in the core module
  2. Utils and workflows files cannot import:
     - Service files (*/services/* or */public_service.py)
     - Django model files (app-level models)
     - the ORM itself: a utils/workflows file must never query the database
  3. background_task imports are only allowed in tasks.py.

Uses `tach map` to get the dependency graph.
"""
import json
import subprocess
import sys

MODULES = {
    'core', 'registry', 'crawling', 'fetching',
    'scheduling', 'attaching', 'front',
}


def get_module(path):
    """Extract the module name (first path component) if it's a known module."""
    first = path.split('/')[0]
    return first if first in MODULES else None


def is_app_level_model(path):
    """Check if path is a Django ORM model file (directly under app root).

    Matches: module/models.py, module/models/__init__.py, module/models/foo.py
    Does NOT match: module/workflows/bar/models.py (workflow-internal models)
    """
    parts = path.split('/')
    if len(parts) < 2 or parts[0] not in MODULES:
        return False
    if len(parts) == 2 and parts[1] == 'models.py':
        return True
    if parts[1] == 'models':
        return True
    return False


def is_allowed_cross_module_target(dep_path):
    """Check if a cross-module import target is allowed."""
    parts = dep_path.split('/')
    if len(parts) < 2:
        return False

    # Django ORM models
    if is_app_level_model(dep_path):
        return True

    # Public API files: app/public_*.py
    if len(parts) == 2 and parts[1].startswith('public_'):
        return True

    # Utils files: app/utils/*.py
    if parts[1] == 'utils':
        return True

    return False


def is_utils_or_workflow(path):
    """Check if the source file is under utils/ or workflows/."""
    parts = path.split('/')
    if len(parts) < 3:
        return False
    return parts[1] in ('utils', 'workflows')


def is_service_target(dep_path):
    """Check if a dependency target is a service file."""
    parts = dep_path.split('/')
    if len(parts) < 2:
        return False
    # app/services/**
    if parts[1] == 'services':
        return True
    # app/public_service.py
    if len(parts) == 2 and parts[1] == 'public_service.py':
        return True
    return False


def check_rule1(dep_map):
    """Rule 1: Cross-module imports must target allowed files."""
    violations = []
    for src, deps in dep_map.items():
        src_mod = get_module(src)
        if not src_mod:
            continue
        for dep in deps:
            dep_mod = get_module(dep)
            if not dep_mod or dep_mod == src_mod:
                continue
            if dep_mod == 'core':
                continue
            if not is_allowed_cross_module_target(dep):
                violations.append({
                    'rule': 1,
                    'source': src,
                    'target': dep,
                    'message': (
                        f'Cross-module import {src_mod} -> {dep_mod}'
                        f' via non-public file'
                    ),
                })
    return violations


def check_rule2(dep_map):
    """Rule 2: Utils/workflows cannot import services or Django models."""
    violations = []
    for src, deps in dep_map.items():
        if not is_utils_or_workflow(src):
            continue
        src_mod = get_module(src)
        if not src_mod:
            continue
        for dep in deps:
            dep_mod = get_module(dep)
            if not dep_mod:
                continue
            if is_service_target(dep):
                violations.append({
                    'rule': 2,
                    'source': src,
                    'target': dep,
                    'message': 'Utils/workflows file imports a service',
                })
            if is_app_level_model(dep):
                violations.append({
                    'rule': 2,
                    'source': src,
                    'target': dep,
                    'message': (
                        'Utils/workflows file imports a Django model'
                    ),
                })
    return violations


def check_rule2_orm_access():
    """Rule 2, grep pass: utils/workflows must never query the database.

    check_rule2 walks `tach map` and skips every dependency outside the project's own modules, so
    importing an *external* app's models (background_task.models, ...) slipped through — and with
    it, ORM queries inside a utils file. Matching the query itself catches that however the import
    is written, and stays quiet on a model imported purely as a type annotation, or on a
    workflow-internal models.py holding plain enums.
    """
    violations = []
    result = subprocess.run(
        [
            'grep', '-rn', '-E', r'\.objects',
            '--include=*.py',
            '--exclude-dir=.venv',
            '--exclude-dir=__pycache__',
            '--exclude-dir=migrations',
            '--exclude-dir=scripts',
            '.',
        ],
        capture_output=True, text=True,
    )
    for line in result.stdout.strip().split('\n'):
        if not line:
            continue
        filepath, _, statement = line.split(':', 2)
        filepath = filepath.lstrip('./')
        if not is_utils_or_workflow(filepath):
            continue
        violations.append({
            'rule': 2,
            'source': filepath,
            'target': statement.strip(),
            'message': 'Utils/workflows file queries the database',
        })
    return violations


def check_rule3():
    """Rule 3: background_task imports only in tasks.py files."""
    violations = []
    result = subprocess.run(
        [
            'grep', '-rn', '-E', r'^from background_task[. ]',
            '--include=*.py',
            '--exclude-dir=.venv',
            '--exclude-dir=__pycache__',
            '--exclude-dir=migrations',
            '--exclude-dir=scripts',
            '.',
        ],
        capture_output=True, text=True,
    )
    for line in result.stdout.strip().split('\n'):
        if not line:
            continue
        filepath = line.split(':')[0]
        filepath = filepath.lstrip('./')
        if filepath.endswith('tasks.py'):
            continue
        if get_module(filepath) == 'core':
            continue
        violations.append({
            'rule': 3,
            'source': filepath,
            'target': 'background_task (external)',
            'message': 'background_task import outside of tasks.py',
        })
    return violations


def main():
    result = subprocess.run(
        ['uv', 'run', 'tach', 'map'],
        capture_output=True, text=True,
        timeout=120,
    )
    if result.returncode != 0:
        print(f'Error running tach map: {result.stderr}', file=sys.stderr)
        sys.exit(2)

    dep_map = json.loads(result.stdout)

    violations = []
    violations.extend(check_rule1(dep_map))
    violations.extend(check_rule2(dep_map))
    violations.extend(check_rule2_orm_access())
    violations.extend(check_rule3())

    if not violations:
        print('All dependency rules passed.')
        sys.exit(0)

    violations.sort(key=lambda v: (v['rule'], v['source']))
    print(f'Found {len(violations)} violation(s):')
    print()
    for v in violations:
        print(f"  Rule {v['rule']}: {v['source']}")
        print(f"    -> {v['target']}")
        print(f"    {v['message']}")
        print()

    sys.exit(1)


if __name__ == '__main__':
    main()
