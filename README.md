# bt_watch

`bt_watch.py` on taustaprosessi, joka valvoo lähistön Bluetooth-laitteita. Se tukee sekä BT Classic- että BLE-laitteita käyttäen BlueZ/DBus-rajapintaa (bleak-kirjasto). Prosessi toimii ilman X-ympäristöä ja voidaan ajaa tavallisena käyttäjänä.

## Asennus

1. Asenna järjestelmäriippuvuudet:
   ```bash
   sudo apt-get update
   sudo apt-get install -y bluetooth bluez python3 python3-venv
   ```
2. Lisää käyttäjä `bluetooth`-ryhmään ja varmista udev-oikeudet (jotta root-oikeuksia ei tarvita jatkuvasti):
   ```bash
   sudo usermod -aG bluetooth $USER
   sudo tee /etc/udev/rules.d/99-bt-watch.rules <<'UDEV'
   SUBSYSTEM=="bluetooth", GROUP="bluetooth", MODE="0660"
UDEV
   sudo udevadm control --reload-rules
   ```
   Kirjaudu ulos ja sisään, jotta ryhmäoikeudet päivittyvät.
3. Luo virtuaaliympäristö ja asenna Python-riippuvuudet:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

## Käyttö

Käynnistä skanneri komennolla:

```bash
python bt_watch.py --config ./config.yaml
```

Asetuksia voi muokata `config.yaml`-tiedostossa tai yliajaa ympäristömuuttujilla (esim. `SCAN_INTERVAL=2.0`).

Moniarvoiset asetukset, kuten `exclude_mac_prefixes`, annetaan pilkulla
eroteltuna listana (esim. `EXCLUDE_MAC_PREFIXES=AA:BB,CC:DD`).

Ohjelma tulostaa `NEW`- ja `LOST`-tapahtumat stdoutiin ja kirjoittaa kaikki tapahtumat JSON Lines -muotoon tiedostoon `bt_watch.log`.

### Simulaattoritila

Ilman fyysisiä BT-laitteita logiikkaa voidaan testata simulaatiolla:

```bash
python bt_watch.py --config ./config.yaml --simulate
```

### Systemd-palvelu

Kopioi `bt_watch.py`, `config.yaml` ja `requirements.txt` esimerkiksi hakemistoon `/opt/bt_watch/`. Asenna systemd-palvelu:

```bash
sudo cp systemd/bt-watch.service /etc/systemd/system/
sudo cp systemd/bt-watch.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now bt-watch.service
```

Palvelu käynnistyy automaattisesti bootissa (`Restart=on-failure`).

## Esimerkkiloki

```
NEW:AA:BB:CC:DD:EE:01:Sensor:-55
LOST:AA:BB:CC:DD:EE:01:Sensor:-55
```

`bt_watch.log` sisältää rivit esimerkiksi:

```
{"event": "NEW", "timestamp": "2024-01-01T00:00:00+00:00", "mac": "AA:BB:CC:DD:EE:01", "name": "Sensor", "rssi_dBm": -55}
```

## Vianetsintä

- Tarkista, että adapteri on päällä: `sudo rfkill list`.
- Jos `bluetoothd` ei ole käynnissä, käynnistä: `sudo systemctl start bluetooth`.
- Jos laite on estetty BIOSissa, ota se käyttöön ja käynnistä kone uudelleen.
- Varmista, että käyttäjä kuuluu `bluetooth`-ryhmään.

## Testaus

Simulaattori mahdollistaa NEW/LOST-logiikan todentamisen ilman laitteita. Yksikkötestit ajetaan `pytest`-komennolla.
