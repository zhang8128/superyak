# Two people, two laptops

How Alex and Sam, each on their own laptop, get from nothing to a first private message and a shared document. **This
page is new, and nobody has walked it across two real laptops;** [some steps couldn't be run](#what-hasnt-been-checked).
Please report what goes wrong on the Discussions page linked from the [README](../README.md#not-invited-yet), leaving
pairing codes out.

## What it costs and what you need

- **Money:** nothing we know of. Superyak is free; Tailscale has a $0 plan for non-commercial use, with sharing on all
  plans (November 2026).
- **Each of you:** a Mac or Linux laptop you may install software on (no Windows; WSL is untried), a terminal, `git`,
  `make`, uv and a free Tailscale account. We haven't timed this. Be on a call for steps 4 to 6.
- **In use:** Alex keeps three windows open, Sam one. Messages wait until both laptops are awake and running them.
- **Privacy:** not end-to-end encrypted. What you send sits in plain files on both laptops; keep patient data out.

## The route: Alex listens, Sam fetches

Alex's home answers on Tailscale's private network. Sam's never listens: it dials Alex's about once a minute to fetch
what's waiting, and within seconds to send what Sam writes. Let Alex be whoever's laptop is awake more. Both need
Tailscale, because Sam's laptop must reach Alex's. A share of Alex's laptop lets Sam reach Alex and not the reverse,
which is all this needs: one listener, and no port to open on your network. Sam could listen too, but that doubles the
setup for nothing. No browser has to trust anything: each talks only to its own laptop, and Sam's home checks Alex's
against the certificate pinned in Alex's card.

**A campus network or university laptop:** we've tested none and don't know if yours allows this. Tailscale connects
outward and can relay over HTTPS, so it may work where incoming connections are blocked, but a network may block it, and
a managed laptop may forbid it. Step 3 ends with a test; if it fails, we have no other tested route.

## The steps

Run everything from the top `superyak` folder, in an ordinary terminal window. Your home lives in `.engram/home` there;
`peer/README.md`'s commands run inside `peer/`, where that path would mean a different home.

**1. Both: install.** Install uv with `curl -LsSf https://astral.sh/uv/install.sh | sh` and open a new terminal. On a
Mac without `git` or `make`, run `xcode-select --install`. Then:
```sh
git clone https://github.com/zhang8128/superyak.git
cd superyak
make setup-peer
```

**2. Both: create your home.** Alex runs this; Sam uses `--username sam --name 'Sam'`.
```sh
uv run --locked --project peer python -m superyak_peer init --username alex --name 'Alex'
```
It asks for a password of 12 or more characters, and there's no reset (`--password-file FILE` reads it from a file
instead). **Sam, don't start your home yet:** a first start gives it an identity, and step 4 refuses one that has it. If
you already ran `make home`, use a second home: `--data-dir .engram/sam` on `init`, `card` and `pair`, and
`HOME_DATA=.engram/sam` on `make home`, the same folder.

**3. Both: connect with Tailscale.** Install [Tailscale](https://tailscale.com/download) and sign in with a personal
account, not a university one: sharing and accepting each take being an admin of your own Tailscale network. On a Mac, if
`tailscale` isn't a command, use `/Applications/Tailscale.app/Contents/MacOS/Tailscale`.
- **Alex:** in the Tailscale [admin console](https://login.tailscale.com/admin/machines), open **Machines**, your
  laptop's menu, **Share**, **Copy invite link**. Send Sam the link and the address from `tailscale ip -4`
  (`100.x.y.z`).
- **Sam:** accept, then run `tailscale ping 100.x.y.z` with those numbers. `pong` means it works, even `via DERP`.

**4. Both: export your card.** The home doesn't need to be running. Alex runs the first line, with your own address. Sam
runs the second, whose `--pull` means no address: this home fetches, and stays that way.
```sh
uv run --locked --project peer python -m superyak_peer card --username alex --endpoint https://100.x.y.z:7437 > alex-card.json
uv run --locked --project peer python -m superyak_peer card --username sam --pull > sam-card.json
```
Each shows `Pairing code:` on that screen only, and the same command shows it again. `--endpoint` is `https://`, the
address, `:7437`, and nothing after. Check it: after pairing it can't change, short of a new home and pairing again. If
Alex's laptop already uses port 7437, pick another now and use it here, as `federation-listen --port N`, and in `tailscale
serve --tcp N tcp://127.0.0.1:N` in step 7.

**5. Both: swap cards, then read your codes.** Send your card file as an attachment, any way you like: it's all public
material. Save theirs in your `superyak` folder. Then read your code aloud on a call, and never send it to an AI agent or
into a chat with one: the code proves the card you hold is the one on that person's screen only if a person reads it
there and types it here, and if it travels as the card did, nothing is compared.

**6. Both: pair.** Alex runs the first line and types Sam's code; Sam runs the second and types Alex's.
```sh
uv run --locked --project peer python -m superyak_peer pair --card sam-card.json --as alex
uv run --locked --project peer python -m superyak_peer pair --card alex-card.json --as sam
```
It names the card's person and address (`at None` for Sam, who has none), then asks for the code. Success says `Paired`.
If the code doesn't match, ask them to read it again, and type only what they read you. Run `card` and `pair` yourself:
they need a real terminal, so from an AI assistant's tools `card` shows no code and `pair` refuses.

**7. Both: start your homes, after `Paired`.** Before step 4, the second line stops with `serves a push peer only`. Alex
needs three windows, one line each, left running: the web page (`--sync` makes it deliver), the door Sam's home dials, and
Tailscale publishing that door. Sam needs only the first line.
```sh
make home HOME_ARGS=--sync
uv run --locked --project peer python -m superyak_peer federation-listen
tailscale serve --tcp 7437 tcp://127.0.0.1:7437
```
- **Alex:** keep `--tcp`: it passes your certificate through untouched, and Sam's home refuses any other.
- **Both:** open http://127.0.0.1:7435 (`localhost` answers "Unrecognized host") and sign in. If `make home` says the
  address is in use, add `HOME_PORT=8080` and open that port. Next time, repeat only this step; Ctrl-C stops a window.
- **Sam, then Alex:** on **Connections**, click **Check delivery now**. Sam should see `Last pulled`, and Alex
  `Fetches from us · last pull`.

**8. Alex, then Sam: a room and a message.**
- **Alex:** **Chats**, **New chat**, a title, tick Sam, **Create chat**. Write something and click **Send
  message**. It says `Waiting for pull` until Sam's home fetches it, within about a minute.
- **Sam:** pages don't update by themselves, so click **Check delivery now** on **Connections**, which also fetches at
  once. Open the room under **Chats** and reply. Alex clicks it too, to see the reply.

**9. Alex, then Sam: a document.** A document here is a **layer**: a title, text and attached files. You turn on a saved
version, called a release, for the people you name. It doesn't go into a room, so tell Sam in the room.
- **Alex:** **My sharing layers**, **New layer**, the title and **What do you want to share?**, tick Sam under **Named
  people**. **Upload a file** takes text, CSV, JSON, PDF, PNG, JPEG or GIF, not Word, 4 MiB in all. Then **Save private
  draft**, **Preview audience**, read **Who would see it**, **Turn on version**.
- **Sam:** click **Check delivery now**, then **Shared spaces**, and open it under **Active releases**. You can read and
  download it, not edit it; Alex changes it by turning on a new version. If Alex clicks **Stop all sharing**, it leaves
  your home at the next fetch, but that can't erase a copy you saved.

## If something goes wrong

- **Sam has no `pong`, or never sees `Last pulled`.** The page may not say why. Check the share, Alex's three windows,
  that Alex paired Sam's card, and that the clocks agree within 5 minutes.
- **`certificate differs`.** Alex's third window isn't the `--tcp` line, or the card is another home's.
- **`Retrying` on a document Sam shared.** A delivery from Sam to Alex has 3 seconds, so a large file can keep failing
  and hold up Sam's later messages. **Stop all sharing** on it and use a smaller file.
- **Show my peer card, or `serve --peer-tls` in `peer/README.md`.** Not on this route: use `card` in a terminal.
  `serve --peer-tls` serves the web page over HTTPS, so your browser warns you, and it can't answer a fetching home.

## What hasn't been checked

- **`card` and `pair` weren't run for this page,** because pairing is a person's to do. They, and every button named
  here, were checked by reading the code, its tests and `--help`.
- **Run on one machine, with no real message:** `init`, and `make home HOME_ARGS=--sync` beside `federation-listen`,
  with the delivery mode set by hand. `--sync` stands in for `peer/README.md`'s `federate` and runs the same loop.
  `peer/tests/test_federate.py` exchanges a room, a reply and a release on one machine; it was read, not run.
- **Tailscale:** from its docs and `--help` on Linux. Not tried: a share, `--tcp` through one (its docs don't say a
  shared-in person can reach it), or anything on a Mac.
- **Not known:** any campus network, how long this takes, and how it behaves on a slow relay.
