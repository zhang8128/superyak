// Superyak browser lane (written into <lane>/preload.cjs by teamd; the worker can read it but not change it).
// NODE_OPTIONS=--require loads it into every node the worker starts. A server that listens on an unspecified
// address (none, '', 0.0.0.0 or ::) binds 127.0.0.1 instead, so nothing a lane starts answers the LAN or the
// tailnet: listen(0) alone binds :: (spike 3). Unix sockets, inherited handles and explicit addresses are left alone.
// It is advisory (a child started without NODE_OPTIONS skips it); teamd's listener check is the backstop.
'use strict';
const net = require('net');
const LOOPBACK = '127.0.0.1';
// Every spelling of an all-zero address: '0', '0.0', '0.0.0.0', '::', '::0', '0:0:0:0:0:0:0:0'.
const zeroAddress = host => {
  const family = net.isIP(host);
  if (family === 4) return host.split('.').every(part => /^(0x0*|0+)$/i.test(part));
  if (family === 6) return host.split(/[:.]/).every(part => part === '' || /^0+$/.test(part));
  return /^(0x0*|0+)(\.(0x0*|0+))*$/i.test(host);                         // '0' and '0.0' are not IPs to net.isIP
};
const unspecified = host => host === undefined || host === null || host === '' || (typeof host === 'string' && zeroAddress(host));
const isPort = value => typeof value === 'number' || (typeof value === 'string' && /^[0-9]+$/.test(value));
const listen = net.Server.prototype.listen;
net.Server.prototype.listen = function (...args) {
  const first = args[0];
  if (args.length === 0 || typeof first === 'function') {                 // listen() / listen(callback)
    return listen.call(this, 0, LOOPBACK, ...args);
  }
  if (isPort(first)) {                                                    // listen(port[, host][, backlog][, cb])
    if (args.length > 1 && (typeof args[1] === 'string' || args[1] === null || args[1] === undefined)) {
      if (unspecified(args[1])) args[1] = LOOPBACK;
    } else {
      args.splice(1, 0, LOOPBACK);
    }
    return listen.apply(this, args);
  }
  if (first && typeof first === 'object' && first.path === undefined && first.fd === undefined &&
      first.handle === undefined && first._handle === undefined && unspecified(first.host)) {
    args[0] = Object.assign({}, first, { host: LOOPBACK });             // listen({port, host})
  }
  return listen.apply(this, args);
};
