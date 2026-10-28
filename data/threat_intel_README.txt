This directory (data/threat_intel/) holds the address lists used for
Objective 4 dataset-match attribution: OFAC_SDN.json, WannaCry.json,
DarknetMarket.json.

The bundled files already contain REAL, sourced addresses (see the
docstring at the top of core/threat_intel.py for full citations):
  - 2 confirmed OFAC SDN addresses (Khorashadizadeh/Ghorbaniyan, the first
    Bitcoin addresses ever sanctioned, Nov 2018) + 2 more from the
    open-source OFAC XBT extractor
  - All 3 hardcoded WannaCry ransomware payout addresses (May 2017)
  - The US government's Silk Road forfeiture address (James Zhong case)

This is a small, hand-picked demo set - not a comprehensive database.
To extend it with the full OFAC SDN list, run:
  https://github.com/0xB10C/ofac-sanctioned-digital-currency-addresses
against Treasury's live data and drop the output into OFAC_SDN.json in
the same {"address": "...", "entity_label": "..."} format.
build_lookup_index() automatically loads whatever JSON is in this folder.
