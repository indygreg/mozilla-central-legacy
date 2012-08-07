# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

TIERS = ['base', 'nspr', 'js', 'platform', 'app']
ACTIONS = ['default', 'export', 'libs', 'tools']


# This is abstracted so the tiers can come from the actual build system
# eventually. We also have this in a separate module because the CLI needs this
# and we don't want to require importing the entire building modules.
class Tiers(object):
    def get_tiers(self):
        return TIERS

    def get_actions(self):
        return ACTIONS
