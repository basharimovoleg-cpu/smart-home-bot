"""
Test script: query Tuya device status, discover DP codes and value types,
then try sending a command.
"""

import json
import os
import sys
from typing import Any

from dotenv import load_dotenv
from tuya_client import TuyaClient, TuyaConfig, TuyaError


def main() -> None:
    load_dotenv()

    config = TuyaConfig(
        access_id=os.getenv("TUYA_ACCESS_ID", ""),
        secret=os.getenv("TUYA_SECRET", ""),
        device_id=os.getenv("TUYA_DEVICE_ID", ""),
        base_url=os.getenv("TUYA_REGION_URL", "https://openapi.tuyaeu.com"),
    )

    client = TuyaClient(config)

    # 1. Get device status
    print("=" * 60)
    print("1. Getting device status...")
    try:
        data = client.get_device_status()
        dps = data.get("result", [])
        print(f"   Success! Got {len(dps)} DP(s):")
        for dp in dps:
            code = dp.get("code")
            value = dp.get("value")
            print(f"   code={code!r}  value={value!r}  type={type(value).__name__}")
    except TuyaError as e:
        print(f"   ERROR: {e}")
        sys.exit(1)

    # 2. Identify switch DPs
    switch_dps = [dp for dp in dps if "switch" in str(dp.get("code", "")).lower()]
    if not switch_dps:
        print("\n   No 'switch' DPs found, using first 2 DPs...")
        switch_dps = dps[:2]

    print(f"\n2. Identified switch DP(s):")
    for dp in switch_dps:
        code = dp.get("code")
        value = dp.get("value")
        print(f"   code={code!r}  value={value!r}  type={type(value).__name__}")

    if not switch_dps:
        print("   No DPs to test!")
        sys.exit(1)

    # 3. Try sending commands with different value types
    print("\n" + "=" * 60)
    print("3. Testing command send...")

    for dp in switch_dps[:1]:  # test just the first one
        code = dp.get("code")
        current = dp.get("value")

        # Determine target value and type to try
        if isinstance(current, bool):
            target = not current
            print(f"\n   DP {code!r}: current={current} (bool), trying target={target} (bool)")
        elif isinstance(current, int) and not isinstance(current, bool):
            target = 0 if current != 0 else 1
            print(f"\n   DP {code!r}: current={current} (int), trying target={target} (int)")
        elif isinstance(current, str):
            target = "false" if current.lower() in ("true", "1", "on") else "true"
            print(f"\n   DP {code!r}: current={current!r} (str), trying target={target!r} (str)")
        else:
            print(f"\n   DP {code!r}: unknown type {type(current).__name__}, value={current!r}")
            continue

        # Try sending as-is (matching type)
        try:
            body = {"commands": [{"code": code, "value": target}]}
            print(f"   Sending: {json.dumps(body)}")
            result = client.send_commands([{"code": code, "value": target}])
            print(f"   ✅ SUCCESS: {result.get('result')}")
        except TuyaError as e:
            print(f"   ❌ FAILED: {e}")

            # Retry with opposite type
            alt_target = not target if isinstance(target, bool) else (1 if target == 0 else 0)
            alt_type = int if isinstance(target, bool) else bool
            print(f"   Retrying with {alt_type.__name__}: {alt_target!r}")
            try:
                body = {"commands": [{"code": code, "value": alt_type(alt_target)}]}
                print(f"   Sending: {json.dumps(body)}")
                result = client.send_commands([{"code": code, "value": alt_type(alt_target)}])
                print(f"   ✅ SUCCESS with {alt_type.__name__}: {result.get('result')}")
            except TuyaError as e2:
                print(f"   ❌ FAILED again: {e2}")

    print("\n" + "=" * 60)
    print("Done.")


if __name__ == "__main__":
    main()