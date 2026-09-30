/* Shared "Record payment" panel (used by Invoices and Subscriptions > Collections).
   RecordPayment.open({id, invoice_number, client, total}, onDone) */
(function(){
  var esc=function(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});};
  var money=function(n){return 'R '+(parseFloat(n)||0).toLocaleString('en-ZA',{minimumFractionDigits:2,maximumFractionDigits:2});};
  var current=null, onDone=null;
  function build(){
    if(document.getElementById('rpModal')) return;
    var d=document.createElement('div');
    d.innerHTML='<div class="hq-drawer" id="rpModal"><div class="hq-drawer-header"><h5 class="hq-drawer-title">Record payment</h5>'+
      '<button type="button" class="btn-close btn-close-white" onclick="HQ.hideDrawer(\'rpModal\')"></button></div>'+
      '<div class="hq-drawer-body"><div id="rpAlert"></div>'+
      '<div class="p-2 mb-3" style="background:#f9fafb;border-radius:8px"><div class="fw-bold" id="rpTitle"></div><div class="h4 mb-0" id="rpAmount"></div><div class="small text-muted">Balance still due</div></div>'+
      '<div class="mb-3"><label class="form-label">Amount received</label><input type="number" min="0.01" step="0.01" class="form-control" id="rpAmt"><div class="form-text">Leave the full balance to mark the invoice paid, or enter less for a part payment.</div></div>'+
      '<div class="mb-3"><label class="form-label">Date the money arrived</label><input type="date" class="form-control" id="rpDate"></div>'+
      '<div class="mb-3"><label class="form-label">How was it paid?</label><select class="form-select" id="rpMethod"><option value="eft">EFT / bank transfer</option><option value="cash">Cash</option><option value="card">Card</option><option value="payfast">PayFast</option><option value="other">Other</option></select></div>'+
      '<div class="mb-3"><label class="form-label">Bank reference <span class="text-muted">(optional)</span></label><input class="form-control" id="rpRef" placeholder="What the client put as reference"></div>'+
      '<div class="mb-3"><label class="form-label">Note <span class="text-muted">(optional)</span></label><input class="form-control" id="rpNote"></div>'+
      '<div class="small text-muted">This counts the money received as revenue on the dashboard and books it in the accounts.</div></div>'+
      '<div class="hq-drawer-footer"><button class="btn btn-secondary" onclick="HQ.hideDrawer(\'rpModal\')">Cancel</button><button class="btn btn-success" id="rpSave">Record payment</button></div></div>'+
      '<div class="hq-backdrop" id="rpModal-bd" onclick="HQ.hideDrawer(\'rpModal\')"></div>';
    while(d.firstChild) document.body.appendChild(d.firstChild);
    document.getElementById('rpSave').onclick=save;
  }
  async function save(){
    var btn=document.getElementById('rpSave'), al=document.getElementById('rpAlert'); al.innerHTML=''; btn.disabled=true;
    try{
      var r=await fetch('/portal/api/invoices/'+current.id+'/record-payment/',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+localStorage.getItem('ims_access')},
        body:JSON.stringify({amount:document.getElementById('rpAmt').value,paid_on:document.getElementById('rpDate').value,method:document.getElementById('rpMethod').value,reference:document.getElementById('rpRef').value,note:document.getElementById('rpNote').value})});
      var d=await r.json().catch(function(){return {};});
      if(r.status===401){ localStorage.clear(); location.href='/portal/login/'; return; }
      if(r.ok){ HQ.hideDrawer('rpModal'); if(onDone) onDone(d); }
      else al.innerHTML='<div class="alert alert-danger">'+esc(d.detail||'Could not record the payment.')+'</div>';
    }catch(e){ al.innerHTML='<div class="alert alert-danger">Could not reach the server.</div>'; }
    btn.disabled=false;
  }
  window.RecordPayment={open:function(inv,cb){
    build(); current=inv; onDone=cb;
    document.getElementById('rpAlert').innerHTML='';
    document.getElementById('rpTitle').textContent=inv.invoice_number+(inv.client?' — '+inv.client:'');
    document.getElementById('rpAmount').textContent=money(inv.total); document.getElementById('rpAmt').value=(parseFloat(inv.total)||0).toFixed(2);
    document.getElementById('rpDate').value=new Date().toISOString().slice(0,10); document.getElementById('rpDate').max=new Date().toISOString().slice(0,10);
    document.getElementById('rpMethod').value='eft'; document.getElementById('rpRef').value=inv.invoice_number||''; document.getElementById('rpNote').value='';
    HQ.showDrawer('rpModal');
  }};
})();
