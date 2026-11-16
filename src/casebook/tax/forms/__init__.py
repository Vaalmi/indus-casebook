"""The official 2025 IRS forms, filled from a line-to-field map per form, read back, and stamped.

The forms are the IRS's own fillable PDFs (`pdfs/`, with their sources and hashes in `pdfs/SOURCES.toml`).
Their field names are opaque (`topmostSubform[0].Page1[0].f1_47[0]`), so each form has a hand-built map,
`maps/<form>.toml`, from a key to the field that holds it. The map is also the review packet's mapping
from inputs to form lines; tests/test_tax_forms.py checks every entry against the label the form itself
gives its field.

Keys:

- **Lines** are the form's own line labels as printed, lower case: "1a", "2b", "11a", "12e", "25a" on the
  1040; "8z" on Schedule 1; "16" and "21" on Schedule D; "15a" on Form 8606. A bare line key is the line's
  amount.
- **A second field on a line** is the line followed by the form's own words for it: "1h_type" (the 1040's
  "Enter type"), "16_3_specify", "7_amount_repaid", "8b_paid_to". Numbered boxes on a line keep the form's
  numbers ("4c_1" is Rollover, "4c_2" QCD, "4c_3" the third box); a yes-or-no pair is "<line>_yes" and
  "<line>_no" ("17_yes" on Schedule D).
- **Table columns** are the line and the column letter: "1b_d" to "1b_h" on Schedule D, "22a_i" to
  "22a_iii" on Schedule 1-A.
- **Headers**: the 1040's "name" (first name and middle initial), "last_name", "ssn", "spouse_name",
  "spouse_last_name", "spouse_ssn", and its address; a schedule's single "Name(s) shown on return" is
  "names" and its number "ssn". The 1040's filing status boxes are "status_single", "status_mfj",
  "status_mfs", "status_hoh" and "status_qss"; its dependents table is "dependent<n>_first_name" and so on.
- **Repeating rows**: Schedule B's "part1_row<n>_payer" and "part1_row<n>_amount" (rows 1 to 14), and
  "part2_row<n>_..." (1 to 15); Form 8949's "part1_row<n>_<a..h>" (rows 1 to 11, columns (a) to (h), (f)
  being the code and (g) the adjustment), its totals "part1_total_<d|e|g|h>", and its boxes "part1_box_a",
  "_b", "_c", "_g", "_h", "_i" and "part2_box_d", "_e", "_f", "_j", "_k", "_l". Part 2 is the same on page 2.

A text value arrives formatted as it should print ("1,234." or "1,234.56"; a 1040 SSN as nine digits,
since its boxes hold nine characters; a schedule's as "000-12-3456"). A bool checks or clears a box.
"""

from casebook.tax.forms.fill import fill, read_back
from casebook.tax.forms.maps import FORMS, FormsError, keys
from casebook.watermark import WATERMARK, stamp, stamped_problems

__all__ = ["FORMS", "WATERMARK", "FormsError", "fill", "keys", "read_back", "stamp", "stamped_problems"]
