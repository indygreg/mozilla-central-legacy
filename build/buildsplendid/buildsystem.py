# ***** BEGIN LICENSE BLOCK *****
# Version: MPL 1.1/GPL 2.0/LGPL 2.1
#
# The contents of this file are subject to the Mozilla Public License Version
# 1.1 (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
# http://www.mozilla.org/MPL/
#
# Software distributed under the License is distributed on an "AS IS" basis,
# WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License
# for the specific language governing rights and limitations under the
# License.
#
# The Original Code is Mozilla build system.
#
# The Initial Developer of the Original Code is Mozilla Foundation.
# Portions created by the Initial Developer are Copyright (C) 2011
# the Initial Developer. All Rights Reserved.
#
# Contributor(s):
#  Gregory Szorc <gps@mozilla.com>
#
# Alternatively, the contents of this file may be used under the terms of
# either the GNU General Public License Version 2 or later (the "GPL"), or
# the GNU Lesser General Public License Version 2.1 or later (the "LGPL"),
# in which case the provisions of the GPL or the LGPL are applicable instead
# of those above. If you wish to allow use of your version of this file only
# under the terms of either the GPL or the LGPL, and not to allow others to
# use your version of this file under the terms of the MPL, indicate your
# decision by deleting the provisiwons above and replace them with the notice
# and other provisions required by the GPL or the LGPL. If you do not delete
# the provisions above, a recipient may use your version of this file under
# the terms of any one of the MPL, the GPL or the LGPL.
#
# ***** END LICENSE BLOCK *****

# This file contains a high-level class, BuildSystem, for interacting with
# the Mozilla build system.

from . import config
from . import extractor
from . import makefile

import logging
import os
import os.path
import subprocess
import traceback

class BuildSystem(object):
    """High-level interface to the build system."""

    __slots__ = (
        # BuildSystemExtractor instance
        'bse',

        # config.BuildConfig instance
        'config',

        # logging.Logger instance
        'logger',
    )

    def __init__(self, conf):
        """Construct an instance from a source and target directory."""
        assert(isinstance(conf, config.BuildConfig))

        self.config = conf
        self.bse = extractor.BuildSystemExtractor(conf)
        self.logger = logging.getLogger(__name__)

    def build(self):
        if not self.bse.is_configured:
            self.configure()

        # TODO make conditional
        self.generate_makefiles()

    def configure(self):
        """Runs configure on the build system."""

        # TODO regenerate configure's from configure.in's if needed

        # Create object directory if it doesn't exist
        if not os.path.exists(self.config.object_directory):
            self.log(logging.WARNING, 'create_object_directory',
                     {'dir':self.config.object_directory},
                     'Creating object directory {dir}')

            os.makedirs(self.config.object_directory)

        configure_path = os.path.join(self.config.source_directory, 'configure')

        env = {}
        for k, v in os.environ.iteritems():
            env[k] = v

        # Tell configure not to load a .mozconfig.
        env['IGNORE_MOZCONFIG'] = '1'

        # Tell configure scripts not to generate Makefiles, as we do that.
        env['DONT_GENERATE_MAKEFILES'] = '1'

        args = self.config.configure_args

        self.log(logging.WARNING, 'configure_begin', {'args': args},
                 'Starting configure: {args}')

        p = subprocess.Popen(
            args,
            cwd=self.config.object_directory,
            executable=configure_path,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT
        )
        while True:
            for line in p.stdout:
                self.log(logging.DEBUG, 'configure_output',
                         {'line': line.strip()},
                         '{line}')

            if p.poll() is not None:
                break

        result = p.wait()

        if result != 0:
            self.log(logging.ERROR, 'configure_error', {'resultcode': result},
                     'Configure Error: {resultcode}')
        else:
            self.log(logging.WARNING, 'configure_finish', {},
                     'Configure finished successfully')

        self.bse.refresh_configure_state()

    def generate_makefiles(self):
        """Generate Makefile's into configured object tree."""

        if not self.bse.is_configured:
            self.configure()

        self.log(logging.WARNING, 'generate_makefiles_begin', {},
                 'Beginning generation of Makefiles')

        for relative, filename, m in self.bse.generate_object_directory_makefiles():
            output_path = os.path.join(self.config.object_directory,
                                      relative, filename)

            # Create output directory
            output_directory = os.path.dirname(output_path)

            if not os.path.exists(output_directory):
                os.makedirs(output_directory)
                self.log(logging.DEBUG, 'mkdir', {'dir': output_directory},
                         'Created directory: {dir}')

            with open(output_path, 'wb') as output:
                for line in m.lines():
                    print >>output, line

            self.log(logging.DEBUG, 'write_makefile',
                     {'path': output_path},
                     'Generated Makefile {path}')

        self.log(logging.WARNING, 'generate_makefile_finish', {},
                 'Finished generation of Makefiles')

    def log(self, level, action, params, format_str):
        self.logger.log(level, format_str,
                        extra={'action': action, 'params': params})
