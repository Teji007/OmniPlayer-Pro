# OmniPlayer Pro — Commercial Distribution Checklist

Owner / original author: **Tejinder Pal Singh**

## Required before selling a proprietary build

- Confirm ownership or written permission for all original code/assets included.
- Obtain and retain the required **commercial PyQt6/Riverbank license** if the app is
  proprietary and distributed commercially. PyQt6 is dual licensed GPLv3/commercial,
  not LGPL.
- Decide exactly how Qt is supplied and verify the license for every Qt module shipped.
- Record the exact FFmpeg build and verify LGPL/GPL/nonfree configuration and source/
  notice obligations.
- Produce a software bill of materials with exact versions.
- Include required upstream license texts in the installer/package.
- Publish a privacy policy if the application or website collects personal data,
  telemetry, analytics, crash reports or online-service information.
- Publish terms of sale/refund/support terms appropriate to the countries where the
  product is sold.
- Review trademarks, artwork, icons, fonts, model weights and web-service terms.
- Review YouTube/other service terms before enabling download or extraction features.
- Test whether each online provider permits the intended commercial use.
- Keep source/notice records for every release build.

## Release package recommendation

LICENSE.txt
EULA.txt
THIRD_PARTY_NOTICES.txt
COMMERCIAL_DISTRIBUTION_CHECKLIST.md
third_party_licenses/  (exact upstream texts for shipped components)
licenses/               (license files for bundled binaries)

This checklist is informational and is not legal advice.
