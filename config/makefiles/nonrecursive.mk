# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

# This file contains make rules for the non-recursive build backend.

DIST_DIR := $(OBJECT_DIR)/dist
DIST_IDL_DIR := $(DIST_DIR)/idl
DIST_INCLUDE_DIR := $(DIST_DIR)/include
DIST_IDL_DIR := $(DIST_DIR)/idl
TEMP_DIR := $(OBJECT_DIR)/tmp

IDL_GENERATE_HEADER := PYTHONPATH=$(TOP_SOURCE_DIR)/other-licenses/ply \
  $(PYTHON) $(TOP_SOURCE_DIR)/xpcom/idl-parser/header.py \
  -I $(DIST_IDL_DIR) --cachedir=$(TEMP_DIR)

# export mimimcs the export tier:
#   * .h files are copied into dist/include
#   * .idl files are copied into dist/idl
#   * .idl files are converted into .h files in dist/include
export: $(EXPORT_TARGETS) $(IDL_DIST_FILES) $(IDL_H_FILES)

.PHONY: $(PHONIES) dirs

