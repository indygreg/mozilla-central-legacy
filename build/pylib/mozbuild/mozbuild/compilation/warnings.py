# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

# This modules provides routines for interacting with compiler warnings.

import json
import os
import os.path
import re
from UserDict import UserDict

from mozbuild.base import Base
from mozbuild.util import hash_file

# Regular expression to strip ANSI color sequences from a string. This is
# needed to properly analyze Clang compiler output, for example.
RE_STRIP_COLORS = re.compile(r'\x1b\[[\d;]+m')

# This captures Clang diagnostics with the standard formatting.
RE_CLANG_WARNING = re.compile(r"""
    (?P<file>[^:]+)
    :
    (?P<line>\d+)
    :
    (?P<column>\d+)
    :
    \swarning:\s
    (?P<message>[^\[]+)
    \[(?P<flag>[^\]]+)
    """, re.X)

RE_MSVC_WARNING = re.compile(r"""
    (?P<file>.*)
    \((?P<line>\d+)\)
    \s:\swarning\s
    (?P<flag>[^:]+)
    :\s
    (?P<message>.*)
    """, re.X)

IN_FILE_INCLUDED_FROM = 'In file included from '

class Warning(dict):
    """Represents an individual compiler warnings."""

    def __init__(self):
        dict.__init__(self)

        self['filename'] = None
        self['line'] = None
        self['column'] = None
        self['message'] = None
        self['flag'] = None

    def __eq__(self, other):
        return self['filename'] == other['filename'] \
                and self['line'] == other['line'] \
                and self['column'] == other['column']

    def __neq__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(tuple(sorted(self.items())))

class WarningsDatabase(object):
    """Holds a collection of warnings.

    The warnings database is a semi-intelligent container that holds warnings
    encountered during builds.

    The warnings database is backed by a JSON file. But, that is transparent
    to consumers.

    To external callers, the warnings database is insert only. When a warning
    is encountered, it is inserted into the database.

    During the course of development, it is common for warnings to change
    slightly as source code changes. For example, line numbers will disagree.
    The WarningsDatabase handles this by storing the hash of a file a warning
    occurred in. At warning insert time, if the hash of the file does not match
    what is stored in the database, the existing warnings for that file are
    purged from the database.
    """
    def __init__(self):
        """Create an empty database."""
        self._files = {}

    def __len__(self):
        i = 0
        for value in self._files.values():
            i += len(value['warnings'])

        return i

    def insert(self, warning, compute_hash=True):
        assert isinstance(warning, Warning)

        filename = warning['filename']

        new_hash = None

        if compute_hash:
            new_hash = hash_file(filename)

        if filename in self._files:
            if new_hash != self._files[filename]['hash']:
                del self._files[filename]

        value = self._files.get(filename, {
            'hash': new_hash,
            'warnings': set(),
        })

        value['warnings'].add(warning)

        self._files[filename] = value

    property
    def warnings(self):
        for value in self._files.values():
            for w in value['warnings']: yield w

    def get_type_counts(self):
        """Returns a mapping of warning types to their counts."""

        types = {}
        for value in self._files.values():
            for warning in value['warnings']:
                count = types.get(warning['flag'], 0)
                count += 1

                types[warning['flag']] = count

        return types

    def serialize(self, fh):
        """Serialize the database to an open file handle."""
        obj = {'files': {}}

        # All this hackery because JSON can't handle sets.
        for k, v in self._files.iteritems():
            obj['files'][k] = {}

            for k2, v2 in v.iteritems():
                normalized = v2

                if k2 == 'warnings':
                    normalized = [w for w in v2]

                obj['files'][k][k2] = normalized

        json.dump(obj, fh, indent=2)

    def deserialize(self, fh):
        """Load serialized content from a handle into the current instance."""
        obj = json.load(fh)

        self._files = obj['files']

        # Normalize data types.
        for filename, value in self._files.iteritems():
            for k, v in value.iteritems():
                if k != 'warnings':
                    continue

                normalized = set()
                for d in v:
                    w = Warning()
                    w.update(d)
                    normalized.add(w)

                self._files[filename]['warnings'] = normalized

    def load_from_file(self, filename):
        """Load the database from a file."""
        with open(filename, 'rb') as fh:
            self.deserialize(fh)

    def save_to_file(self, filename):
        """Save the database to a file."""
        with open(filename, 'wb') as fh:
            self.serialize(fh)

class WarningsCollector(object):
    """Collects warnings from text data.

    Instances of this class receive data (usually the output of compiler
    invocations) and parse it into warnings and add these warnings to a
    database.

    The collector works by incrementally receiving data, usually line-by-line
    output from the compiler. Therefore, it can maintain state to parse
    multi-line warning messages.

    Currently, it just supports parsing Clang's single line warnings.
    """
    def __init__(self, database=None, objdir=None, resolve_files=True):
        self.database = database
        self.objdir = objdir
        self.resolve_files = resolve_files
        self.included_from = []

        if database is None:
            self.database = WarningsDatabase()

    def process_line(self, line):
        """Take a line of text and process it for a warning."""

        filtered = RE_STRIP_COLORS.sub('', line)

        # Clang warnings in files included from the one(s) being compiled will
        # start with "In file included from /path/to/file:line:". Here, we
        # record those.
        if filtered.startswith(IN_FILE_INCLUDED_FROM):
            included_from = filtered[len(IN_FILE_INCLUDED_FROM):]

            parts = included_from.split(':')

            self.included_from.append(parts[0])

            return

        warning = Warning()
        filename = None

        # TODO make more efficient so we run minimal regexp matches.
        match_clang = RE_CLANG_WARNING.match(filtered)
        match_msvc = RE_MSVC_WARNING.match(filtered)
        if match_clang:
            d = match_clang.groupdict()

            filename = d['file']
            warning['line'] = int(d['line'])
            warning['column'] = int(d['column'])
            warning['flag'] = d['flag']
            warning['message'] = d['message'].rstrip()

        elif match_msvc:
            d = match_msvc.groupdict()

            filename = d['file']
            warning['line'] = int(d['line'])
            warning['flag'] = d['flag']
            warning['message'] = d['message'].rstrip()
        else:
            self.included_from = []
            return None

        filename = os.path.normpath(filename)

        # Sometimes we get relative includes. These typically point to files in
        # the object directory. We try to resolve the relative path.
        if not os.path.isabs(filename):
            filename = self._normalize_relative_path(filename)

        if not os.path.exists(filename) and self.resolve_files:
            raise Exception('Could not find file containing warning: %s' %
                    filename)

        warning['filename'] = filename

        self.database.insert(warning, compute_hash=self.resolve_files)

        return warning

    def _normalize_relative_path(self, filename):
        # Special case files in dist/include.
        idx = filename.find('/dist/include')
        if idx != -1:
            return self.objdir + filename[idx:]

        for included_from in self.included_from:
            source_dir = os.path.dirname(included_from)

            candidate = os.path.normpath(os.path.join(source_dir, filename))

            if os.path.exists(candidate):
                return candidate

        return filename

class Warnings(Base):
    """High-level interface to warnings system."""

    def __init__(self, config):
        Base.__init__(self, config)

        self._database = None
        self._path = self._get_state_filename('warnings.json')

    @property
    def database(self):
        if self._database:
            return self._database

        self._database = WarningsDatabase()

        if os.path.exists(self._path):
            self._database.load_from_file(self._path)

        return self._database

    def save(self):
        self.database.save_to_file(self._path)
