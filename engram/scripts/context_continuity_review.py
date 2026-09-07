#!/usr/bin/env python3
"""Render captured arm-label-blinded answers for local human review; no model calls."""
import argparse
import hashlib
import json
from pathlib import Path


PAGE = r'''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Engram continuity review</title>
<style>
:root{font:16px/1.5 system-ui;color:#23312b;background:#f4f5f0}body{max-width:960px;margin:auto;padding:24px}
h1{font-size:28px}p{max-width:80ch}button,select,textarea{font:inherit;border:1px solid #9ca99d;border-radius:6px;padding:8px;background:white}
button{cursor:pointer}button:disabled{opacity:.4;cursor:default}nav,.controls{display:flex;gap:12px;flex-wrap:wrap;align-items:center}
article{background:white;border:1px solid #d4dcd4;border-radius:12px;padding:24px;margin:20px 0}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.5 ui-monospace,monospace;background:#f1f3ee;padding:14px;border-radius:6px}
label{display:block;margin:14px 0}textarea{display:block;width:95%;height:90px}summary{cursor:pointer}
#status{color:#59685d}#notice{color:#8c4220}.small{font-size:14px;color:#59685d}
</style>
<h1>Engram continuity review</h1>
<p>Judge each answer against its original sources. Check speaker attribution,
revisions, unresolved disagreements, recent referents, quoted instructions, and
personal meaning. The comparison method is hidden by label, though context formatting
may reveal it. No answer has an automatic correctness rating.</p>
<p class="small">Ratings stay in this browser when storage is available. Export them to keep a portable copy.
Nothing is sent over the network. Existing exported ratings can be imported.</p>
<div class="controls"><label>Show <select id="filter"><option value="captured">Captured answers</option><option value="unrated">Unrated captured answers</option><option value="all">All cells, including failures</option></select></label>
<button id="export">Export ratings</button><label>Import ratings <input id="import" type="file" accept="application/json"></label></div>
<p id="notice" role="status"></p><nav><button id="previous">Previous</button><span id="status"></span><button id="next">Next</button></nav>
<article id="card"><p class="small" id="identity"></p><h2 id="question"></h2>
<h3>Captured answer</h3><pre id="answer"></pre><h3>Original expected sources</h3><pre id="originals"></pre>
<details><summary>Inspect the supplied context</summary><pre id="context"></pre></details>
<label>Factual correctness <select id="correctness"><option value="">Unrated</option><option value="correct">Correct and supported</option><option value="incorrect">Incorrect or incomplete</option><option value="uncertain">Needs adjudication</option><option value="unavailable">No usable answer</option></select></label>
<label>Conversational continuity <select id="continuity"><option value="">Unrated</option><option value="appropriate">Preserves meaning and responds naturally</option><option value="inappropriate">Misses meaning or breaks continuity</option><option value="uncertain">Needs adjudication</option><option value="not_applicable">Not applicable</option></select></label>
<label>Evidence / notes <textarea id="notes" placeholder="Explain any error, lost constraint, or change in personal meaning."></textarea></label>
</article><script id="packet" type="application/json">__PACKET__</script>
<script>
'use strict';
const packet=JSON.parse(document.getElementById('packet').textContent), records=packet.records;
const $=id=>document.getElementById(id), key='engram-continuity-'+packet.sha256;
let ratings={}, index=0, visible=records;
try {ratings=JSON.parse(localStorage.getItem(key)||'{}')} catch(e) {$('notice').textContent='Browser storage is unavailable; export ratings before closing.'}
function draw(){
 visible=records.filter(r=>$('filter').value==='all'||(r.answer!=null&&($('filter').value==='captured'||!ratings[r.review_id]?.correctness||!ratings[r.review_id]?.continuity)));
 index=Math.max(0,Math.min(index,visible.length-1));
 const r=visible[index], completed=records.filter(x=>ratings[x.review_id]?.correctness&&ratings[x.review_id]?.continuity).length;
 $('status').textContent=(r?`${index+1} of ${visible.length}`:'No answers in this filter')+` · ${completed}/${records.length} fully rated`;
 $('previous').disabled=index===0; $('next').disabled=index>=visible.length-1; $('card').hidden=!r;
 if(!r)return;
 $('identity').textContent=`Review ${r.review_id} · ${r.split}`;
 $('question').textContent=r.question; $('answer').textContent=r.answer??JSON.stringify(r.error??'No captured answer',null,2);
 $('originals').textContent=JSON.stringify(r.expected_originals,null,2);$('context').textContent=JSON.stringify(r.supplied_context,null,2);
 const grade=ratings[r.review_id]||{};
 $('correctness').value=grade.correctness||'';$('continuity').value=grade.continuity||'';$('notes').value=grade.notes||'';
}
function save(){
 const r=visible[index];if(!r)return;
 ratings[r.review_id]={correctness:$('correctness').value||null,continuity:$('continuity').value||null,notes:$('notes').value};
 try{localStorage.setItem(key,JSON.stringify(ratings))}catch(e){$('notice').textContent='Browser storage failed; export ratings before closing.'}
 // Keep this answer visible until navigation, including while entering notes.
 const completed=records.filter(x=>ratings[x.review_id]?.correctness&&ratings[x.review_id]?.continuity).length;
 $('status').textContent=`${index+1} of ${visible.length} · ${completed}/${records.length} fully rated`;
}
for(const id of ['correctness','continuity','notes'])$(id).addEventListener('input',save);
$('filter').onchange=()=>{index=0;draw()};
$('previous').onclick=()=>{index--;draw()};$('next').onclick=()=>{if($('filter').value!=='unrated')index++;else if(!ratings[visible[index].review_id]?.correctness||!ratings[visible[index].review_id]?.continuity)index++;draw()};
$('export').onclick=()=>{
 const blob=new Blob([JSON.stringify({schema_version:1,packet_sha256:packet.sha256,human_ratings:ratings},null,2)],{type:'application/json'});
 const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='engram-human-continuity-ratings.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);
};
$('import').onchange=async event=>{
 try{
  const file=event.target.files[0];if(!file)return;
  const value=JSON.parse(await file.text());
  if(value.packet_sha256!==packet.sha256||!value.human_ratings||typeof value.human_ratings!=='object'||Array.isArray(value.human_ratings))throw Error('Ratings belong to a different review packet');
  const ids=new Set(records.map(r=>r.review_id));
  for(const [id,g] of Object.entries(value.human_ratings))if(!ids.has(id)||!g||typeof g!=='object'||![null,'correct','incorrect','uncertain','unavailable'].includes(g.correctness)||![null,'appropriate','inappropriate','uncertain','not_applicable'].includes(g.continuity)||typeof g.notes!=='string')throw Error('Invalid human rating');
  ratings=value.human_ratings;try{localStorage.setItem(key,JSON.stringify(ratings))}catch(e){}
  $('notice').textContent='Imported ratings.';index=0;draw();
 }catch(e){$('notice').textContent=e.message}
};
draw();
</script></html>'''


def render(source, destination):
    raw = Path(source).read_bytes()
    records = json.loads(raw)
    packet = json.dumps({"sha256": hashlib.sha256(raw).hexdigest(), "records": records}, ensure_ascii=False)
    # Context and model output are data, including any apparent HTML/script tags.
    packet = packet.replace("<", "\\u003c").replace("&", "\\u0026")
    Path(destination).write_text(PAGE.replace("__PACKET__", packet))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Captured blinded-review.json")
    parser.add_argument("destination", type=Path, help="Standalone HTML output")
    args = parser.parse_args()
    render(args.source, args.destination)
