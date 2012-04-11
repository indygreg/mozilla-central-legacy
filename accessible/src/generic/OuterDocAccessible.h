/* -*- Mode: C++; tab-width: 2; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* ***** BEGIN LICENSE BLOCK *****
 * Version: MPL 1.1/GPL 2.0/LGPL 2.1
 *
 * The contents of this file are subject to the Mozilla Public License Version
 * 1.1 (the "License"); you may not use this file except in compliance with
 * the License. You may obtain a copy of the License at
 * http://www.mozilla.org/MPL/
 *
 * Software distributed under the License is distributed on an "AS IS" basis,
 * WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License
 * for the specific language governing rights and limitations under the
 * License.
 *
 * The Original Code is mozilla.org code.
 *
 * The Initial Developer of the Original Code is
 * Netscape Communications Corporation.
 * Portions created by the Initial Developer are Copyright (C) 2003
 * the Initial Developer. All Rights Reserved.
 *
 * Contributor(s):
 *   Original Author: Aaron Leventhal (aaronl@netscape.com)
 *
 * Alternatively, the contents of this file may be used under the terms of
 * either of the GNU General Public License Version 2 or later (the "GPL"),
 * or the GNU Lesser General Public License Version 2.1 or later (the "LGPL"),
 * in which case the provisions of the GPL or the LGPL are applicable instead
 * of those above. If you wish to allow use of your version of this file only
 * under the terms of either the GPL or the LGPL, and not to allow others to
 * use your version of this file under the terms of the MPL, indicate your
 * decision by deleting the provisions above and replace them with the notice
 * and other provisions required by the GPL or the LGPL. If you do not delete
 * the provisions above, a recipient may use your version of this file under
 * the terms of any one of the MPL, the GPL or the LGPL.
 *
 * ***** END LICENSE BLOCK ***** */

#ifndef MOZILLA_A11Y_OUTERDOCACCESSIBLE_H_
#define MOZILLA_A11Y_OUTERDOCACCESSIBLE_H_

#include "nsAccessibleWrap.h"

namespace mozilla {
namespace a11y {

/**
 * Used for <browser>, <frame>, <iframe>, <page> or editor> elements.
 * 
 * In these variable names, "outer" relates to the OuterDocAccessible as
 * opposed to the nsDocAccessibleWrap which is "inner". The outer node is
 * a something like tags listed above, whereas the inner node corresponds to
 * the inner document root.
 */

class OuterDocAccessible : public nsAccessibleWrap
{
public:
  OuterDocAccessible(nsIContent* aContent, nsDocAccessible* aDoc);
  virtual ~OuterDocAccessible();

  NS_DECL_ISUPPORTS_INHERITED

  // nsIAccessible
  NS_IMETHOD GetActionName(PRUint8 aIndex, nsAString& aName);
  NS_IMETHOD GetActionDescription(PRUint8 aIndex, nsAString& aDescription);
  NS_IMETHOD DoAction(PRUint8 aIndex);

  // nsAccessNode
  virtual void Shutdown();

  // nsAccessible
  virtual mozilla::a11y::role NativeRole();
  virtual nsresult GetAttributesInternal(nsIPersistentProperties *aAttributes);
  virtual nsAccessible* ChildAtPoint(PRInt32 aX, PRInt32 aY,
                                     EWhichChildAtPoint aWhichChild);

  virtual void InvalidateChildren();
  virtual bool AppendChild(nsAccessible *aAccessible);
  virtual bool RemoveChild(nsAccessible *aAccessible);

  // ActionAccessible
  virtual PRUint8 ActionCount();

protected:
  // nsAccessible
  virtual void CacheChildren();
};

} // namespace a11y
} // namespace mozilla

#endif  