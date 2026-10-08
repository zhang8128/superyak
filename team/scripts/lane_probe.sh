#!/bin/bash
# Browser-lane spike probes. Runs INSIDE Claude Code's sandbox (one Bash call from `claude -p`), so every line
# shows what a lane worker could really do. Prints one line per probe: "name<TAB>expect<TAB>exit code<TAB>output".
# Arguments come from the environment set by lane_spike.py, never from the model.
set -u
probe() {  # probe NAME EXPECT COMMAND...  (EXPECT is ok|fail|info; the driver judges) -- runs the command once
  local name="$1" expect="$2"; shift 2
  local out code
  out=$("$@" 2>&1); code=$?
  out=$(printf '%s' "$out" | head -c 300 | tr '\n\t' '  ')
  printf '%s\t%s\t%s\t%s\n' "$name" "$expect" "$code" "$out"
}
NODE=${SPIKE_NODE:-node}
probe tmpdir_env info printenv TMPDIR
probe tmpdir_node info "$NODE" -e "console.log(require('os').tmpdir())"
probe unix_listen_tmp ok "$NODE" -e "const p=require('path').join(require('os').tmpdir(),'spike.sock');try{require('fs').unlinkSync(p)}catch(e){};require('net').createServer().listen(p,function(){console.log(p);process.exit(0)}).on('error',e=>{console.log(e.code);process.exit(1)})"
probe tcp_listen_loopback ok "$NODE" -e "require('net').createServer().listen(0,'127.0.0.1',function(){console.log(this.address().port);process.exit(0)}).on('error',e=>{console.log(e.code);process.exit(1)})"
probe tcp_listen_any info "$NODE" -e "require('net').createServer().listen(0,function(){console.log(JSON.stringify(this.address()));process.exit(0)}).on('error',e=>{console.log(e.code);process.exit(1)})"
probe canary_localhost info "$NODE" -e "require('net').connect(+process.env.SPIKE_CANARY_PORT,'127.0.0.1').on('data',d=>{console.log(String(d).trim());process.exit(0)}).on('error',e=>{console.log(e.code);process.exit(1)})"
probe egress_domain_curl fail curl -sSf --max-time 5 -o /dev/null -w '%{http_code}' https://example.com
probe egress_ip_curl fail curl -sSf --max-time 5 -o /dev/null -w '%{http_code}' http://1.1.1.1
probe egress_domain_node fail "$NODE" -e "fetch('https://example.com').then(()=>process.exit(0),e=>{console.log(String(e.cause&&e.cause.code||e));process.exit(1)})"
probe egress_ip_node fail "$NODE" -e "require('net').connect(80,'1.1.1.1').on('connect',()=>process.exit(0)).on('error',e=>{console.log(e.code);process.exit(1)}).setTimeout(5000,()=>process.exit(2))"
probe dns_lookup info "$NODE" -e "require('dns').lookup('example.com',(e,a)=>{console.log(e?e.code:a);process.exit(e?1:0)})"
for sock in ${SPIKE_SOCKETS:-}; do
  probe "socket:$sock" fail "$NODE" -e "require('net').connect(process.argv[1]).on('connect',()=>process.exit(0)).on('error',e=>{console.log(e.code);process.exit(1)})" "$sock"
done
probe home_list fail ls "$HOME"
probe npm_cache_write ok sh -c 'mkdir -p "$npm_config_cache" && touch "$npm_config_cache/spike" && echo "$npm_config_cache"'
probe darwin_user_temp_dir info getconf DARWIN_USER_TEMP_DIR
if [ -n "${SPIKE_PLAYWRIGHT:-}" ]; then
  for sandbox in off on; do
    probe "chrome_sandbox_$sandbox" "$([ $sandbox = off ] && echo ok || echo info)" "$NODE" "${SPIKE_CHROME_SCRIPT}" "$sandbox"
  done
  probe chrome_persistent_profile info "$NODE" "${SPIKE_CHROME_SCRIPT}" off persistent
  # The same launch with Playwright's and Chrome's own logs, kept whole in a file the driver prints after the run.
  probe chrome_debug_log info sh -c 'DEBUG="pw:browser*" SPIKE_CHROME_DEBUG=1 "$0" "$1" off > "$SPIKE_LOG" 2>&1; echo "exit $?"' "$NODE" "${SPIKE_CHROME_SCRIPT}"
fi
echo "done"
