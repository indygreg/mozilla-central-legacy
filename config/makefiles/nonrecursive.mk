# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

# This file contains make rules for the non-recursive build backend.

DIST_DIR := $(OBJECT_DIR)/dist
DIST_IDL_DIR := $(DIST_DIR)/idl
DIST_INCLUDE_DIR := $(DIST_DIR)/include
DIST_IDL_DIR := $(DIST_DIR)/idl
DIST_COMPONENTS_DIR := $(DIST_DIR)/bin/components
TEMP_DIR := $(OBJECT_DIR)/tmp

IDL_GENERATE_HEADER := PYTHONPATH=$(TOP_SOURCE_DIR)/other-licenses/ply \
  $(PYTHON) $(TOP_SOURCE_DIR)/xpcom/idl-parser/header.py \
  -I $(DIST_IDL_DIR) --cachedir=$(TEMP_DIR)

IDL_GENERATE_XPT := $(PYTHON_PATH) \
  $(PLY_INCLUDE) \
  -I$(TOP_SOURCE_DIR)/xpcom/typelib/xpt/tools \
  $(LIBXUL_DIST)/sdk/bin/typelib.py $(XPIDL_FLAGS)

IDL_UPDATE_INTERFACES_MANIFEST := $(PYTHON) $(TOP_SOURCE_DIR)/config/buildlist.py \
  $(DIST_COMPONENTS_DIR)/interfaces.manifest

IDL_UPDATE_CHROME_MANIFEST := $(PYTHON) $(TOP_SOURCE_DIR)/config/buildlist.py \
  $(DIST_COMPONENTS_DIR)/chrome.manifest "manifest components/interfaces.manifest"

# export mimimcs the export tier:
#   * .h files are copied into dist/include
#   * .idl files are copied into dist/idl
#   * .idl files are converted into .h files in dist/include
export: $(EXPORT_TARGETS) $(IDL_H_FILES) $(IDL_DIST_IDL_FILES) $(IDL_DIST_H_FILES)

# XPT files are linked together.
libs: $(IDL_XPT_FILES) $(IDL_XPT_INSTALL_FILES) $(CPP_OBJECT_FILES)

.PHONY: $(PHONIES) dirs

