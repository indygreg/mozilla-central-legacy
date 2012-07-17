# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

class BuildSystem(object):
    def generate_makefiles(self):
        """Generate Makefiles into configured object tree."""

        for relative, filename, m in self.bse.generate_object_directory_makefiles():
            output_path = os.path.join(self.config.object_directory,
                                      relative, filename)

            # Create output directory
            output_directory = os.path.dirname(output_path)

            if not os.path.exists(output_directory):
                os.makedirs(output_directory)

            with open(output_path, 'wb') as output:
                for line in m.lines():
                    print >>output, line
