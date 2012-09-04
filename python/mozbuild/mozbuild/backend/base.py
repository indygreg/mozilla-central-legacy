# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

class BuildBackend(object):
    """Abstract base class for build backends.

    A build backend is merely a consumer of the build configuration (the output
    of the frontend processing). It does something with said data. What exactly
    is the discretion of the specific implementation.
    """

    def consume(self, objs):
        """Consume a stream of BuildConfiguration instances.

        This is the main method of the interface. This is what takes the
        frontend output and does something with it.
        """
        raise NotImplemented('%s must implement consume()' % __name__)
