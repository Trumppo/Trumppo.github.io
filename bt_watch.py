#!/usr/bin/env python3
"""
Bluetooth device watcher.

Skannaa ympäristön Bluetooth-laitteita ja raportoi uudet sekä kadonneet
laitteet. Toteutus käyttää Bleak-kirjaston BlueZ-backendiä ja toimii
headless-tilassa.

Käynnistys:
    python bt_watch.py --config ./config.yaml [--simulate]
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

import yaml
from bleak import BleakScanner


@dataclass
class Observation:
    """Yhden havainnon tiedot."""

    timestamp: datetime
    mac: str
    name: str
    address_type: str
    rssi: int


class DeviceTracker:
    """Seuraa havaittuja laitteita ja tuottaa NEW/LOST-tapahtumat."""

    def __init__(self, grace_seconds: int, weak_grace_seconds: int):
        self.devices: Dict[str, Dict[str, object]] = {}
        self.grace = grace_seconds
        self.weak_grace = weak_grace_seconds

    def new_scan(self) -> None:
        for info in self.devices.values():
            info["seen"] = False

    def update(self, obs: Observation) -> None:
        info = self.devices.setdefault(
            obs.mac,
            {
                "consecutive": 0,
                "last_rssi": obs.rssi,
                "name": obs.name,
                "address_type": obs.address_type,
                "active": False,
            },
        )
        info["last_seen"] = obs.timestamp
        info["last_rssi"] = obs.rssi
        info["name"] = obs.name
        info["address_type"] = obs.address_type
        info["seen"] = True

    def finalize_scan(self) -> List[Dict[str, object]]:
        events: List[Dict[str, object]] = []
        for mac, info in self.devices.items():
            if info["seen"]:
                prev = info.get("consecutive", 0)
                info["consecutive"] = prev + 1
                if not info.get("active") and info["consecutive"] >= 2:
                    info["active"] = True
                    events.append(
                        {
                            "type": "NEW",
                            "mac": mac,
                            "name": info["name"],
                            "rssi": info["last_rssi"],
                        }
                    )
            else:
                info["consecutive"] = 0
        return events

    def check_lost(self, now: datetime) -> List[Dict[str, object]]:
        events: List[Dict[str, object]] = []
        for mac in list(self.devices.keys()):
            info = self.devices[mac]
            last = info.get("last_seen")
            if last is None:
                continue
            rssi = info.get("last_rssi", -100)
            grace = self.weak_grace if rssi < -90 else self.grace
            if (now - last).total_seconds() > grace:
                events.append(
                    {
                        "type": "LOST",
                        "mac": mac,
                        "name": info.get("name", "N/A"),
                        "rssi": rssi,
                    }
                )
                del self.devices[mac]
        return events


class SimulatedScanner:
    """Tuottaa synteettisiä havaintoja testikäyttöön."""

    def __init__(self, seed: int = 0):
        import random

        self.random = random.Random(seed)
        self.active: Dict[str, Dict[str, object]] = {}
        self.counter = 0

    def _new_mac(self) -> str:
        self.counter += 1
        return f"02:00:00:00:00:{self.counter:02X}"

    def generate(self) -> List[Observation]:
        ts = datetime.now(timezone.utc)
        observations: List[Observation] = []
        # randomly remove devices
        for mac in list(self.active.keys()):
            info = self.active[mac]
            if self.random.random() < 0.1:
                del self.active[mac]
                continue
            # vary rssi slightly
            info["rssi"] += self.random.randint(-2, 2)
            observations.append(
                Observation(ts, mac, info["name"], "public", info["rssi"])
            )
        # randomly add new devices
        if self.random.random() < 0.3:
            mac = self._new_mac()
            rssi = self.random.randint(-80, -40)
            name = f"Sim{mac[-2:]}"
            self.active[mac] = {"name": name, "rssi": rssi}
            observations.append(Observation(ts, mac, name, "public", rssi))
        return observations


class BTWatcher:
    def __init__(self, config: Dict[str, object], simulate: bool = False):
        self.scan_interval = float(config.get("scan_interval", 1.0))
        self.min_rssi = int(config.get("min_rssi_dBm", -100))
        self.exclude_prefixes = [p.lower() for p in config.get("exclude_mac_prefixes", [])]
        self.adapter = config.get("adapter", "hci0")
        self.log_path = config.get("log_path", "./bt_watch.log")
        self.tracker = DeviceTracker(
            int(config.get("grace_seconds", 10)),
            int(config.get("weak_signal_grace_seconds", 20)),
        )
        self.simulate = simulate
        self.simulator = SimulatedScanner() if simulate else None
        self.stop_event = asyncio.Event()
        self.log_file = open(self.log_path, "a", buffering=1)

    async def scan_once(self) -> List[Observation]:
        if self.simulate and self.simulator:
            await asyncio.sleep(self.scan_interval)
            return self.simulator.generate()
        devices = await BleakScanner.discover(
            timeout=self.scan_interval,
            adapter=self.adapter,
            return_adv=True,
            scanning_filter={"Transport": "auto"},
        )
        observations: List[Observation] = []
        ts = datetime.now(timezone.utc)
        for device, adv in devices:
            mac = device.address
            if any(mac.lower().startswith(p) for p in self.exclude_prefixes):
                continue
            rssi = device.rssi if device.rssi is not None else -1000
            if rssi < self.min_rssi:
                continue
            name = device.name or adv.local_name or "N/A"
            addr_type = adv.address_type or device.metadata.get("address_type", "N/A")
            observations.append(Observation(ts, mac, name, addr_type, rssi))
        return observations

    def log_json(self, data: Dict[str, object]) -> None:
        self.log_file.write(json.dumps(data) + "\n")
        self.log_file.flush()

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self.stop_event.set)

        while not self.stop_event.is_set():
            self.tracker.new_scan()
            observations = await self.scan_once()
            for obs in observations:
                self.tracker.update(obs)
                self.log_json(
                    {
                        "event": "OBSERVATION",
                        "timestamp": obs.timestamp.isoformat(),
                        "mac": obs.mac,
                        "name": obs.name,
                        "address_type": obs.address_type,
                        "rssi_dBm": obs.rssi,
                    }
                )
            for event in self.tracker.finalize_scan():
                line = f"NEW:{event['mac']}:{event['name']}:{event['rssi']}"
                print(line, flush=True)
                self.log_json(
                    {
                        "event": "NEW",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "mac": event["mac"],
                        "name": event["name"],
                        "rssi_dBm": event["rssi"],
                    }
                )
            for event in self.tracker.check_lost(datetime.now(timezone.utc)):
                line = f"LOST:{event['mac']}:{event['name']}:{event['rssi']}"
                print(line, flush=True)
                self.log_json(
                    {
                        "event": "LOST",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "mac": event["mac"],
                        "name": event["name"],
                        "rssi_dBm": event["rssi"],
                    }
                )
        self.log_file.close()


def load_config(path: str) -> Dict[str, object]:
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    # ympäristömuuttujat
    for key in list(cfg.keys()):
        env_key = key.upper()
        if env_key in os.environ:
            value = os.environ[env_key]
            if isinstance(cfg[key], list):
                cfg[key] = [v.strip() for v in value.split(",") if v.strip()]
            elif isinstance(cfg[key], (int, float)):
                cfg[key] = type(cfg[key])(value)
            else:
                cfg[key] = value
    return cfg


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Bluetooth watcher")
    parser.add_argument("--config", required=True, help="Polku YAML-konfiguraatioon")
    parser.add_argument("--simulate", action="store_true", help="Käytä simulaattoria")
    args = parser.parse_args()

    config = load_config(args.config)
    watcher = BTWatcher(config, simulate=args.simulate)
    asyncio.run(watcher.run())


if __name__ == "__main__":
    main()
