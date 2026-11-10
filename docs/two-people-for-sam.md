# If Andy asked you to try Superyak with him

A note for the second person, before you open [the steps](two-people.md). In those steps Andy is Alex and you are Sam.
Please tell him what was unclear, or where you stopped: that's what this first walk is for.

## What it is

Superyak gives each of you a "home": a small program on your own laptop that keeps your chats and documents in files
there, not on a company's server. Your home and Andy's talk to each other directly. When you're done you'll have a chat
room with him, with one message from you in it.

It isn't end-to-end encrypted: what you write sits in plain files on both laptops. Please keep patient data and anything
you'd mind leaving on Andy's laptop out of it.

## What it takes

- **About 30 minutes, we think**, with Andy on a call for the middle part (reading each other a code). Nobody has timed a
  whole walk yet; you'd be the first.
- **A Mac or Linux laptop** you may install software on. Windows isn't tried yet.
- **Nothing that costs money.** You'll install uv (a Python installer), `git` and `make` if you don't have them, and
  Tailscale. About 400 MB lands on your disk, most of it Python and its packages. On fast broadband the install took
  seconds when we timed it; on a slow link, the download is what takes the time.
- Your home only runs while its terminal window is open, and messages wait until both laptops are awake.

## The part that takes thought: Tailscale (step 3)

Your laptop has to reach Andy's, and Tailscale is how. It's a free app that makes a private network between machines
that trust each other, without opening anything on your home network.

- **Make a personal Tailscale account**, not a university or work one. Accepting a share needs you to be the admin of your
  own Tailscale network, and a managed account usually won't let you.
- **Andy sends you an invite link** that shares one machine: his laptop. Accepting it lets your laptop reach that one
  laptop. It doesn't let him reach yours, and it doesn't show him anything else of yours.
- **Then you test it:** `tailscale ping` with the address he sends you. `pong` means it works, even if it says `via DERP`.
  If you're on a campus network and it fails, tell him: we have no other tested route yet.

## What you and Andy type

Each home makes a card, a small file you swap any way you like; it's all public. Then, on the call, Andy reads you his
pairing code from his screen, and you type it into your terminal; you read yours and he types it. That's how each of you
knows the other's card is really theirs. Read codes aloud only. Never paste one into a chat, an email or an AI assistant:
a code that travels the way the card did proves nothing.

## Leaving

Stop your home any time with Ctrl-C in its window. To leave for good, delete the `superyak` folder, which holds your home,
and remove Andy's shared machine in your Tailscale admin console.

When you're ready: [the steps](two-people.md#the-steps). You are Sam.
