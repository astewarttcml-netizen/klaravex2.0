/* Klaravex: on CF7 submit → prefill Calendly + reveal booking */
(function(){
  if (!/\/contact\//.test(location.pathname)) return;

  document.addEventListener('wpcf7mailsent', function(e){
    var data = e.detail && e.detail.inputs ? e.detail.inputs : [];
    var get = function(n){ var f=data.find(function(x){return x.name===n;}); return f?f.value:''; };
    var name  = get('your-name');
    var email = get('your-email');

    var wrap = document.querySelector('.klaravex-calendly-embed');
    if (!wrap) return;
    var iframe = wrap.querySelector('iframe');

    // Build prefilled Calendly URL
    if (iframe) {
      var src = iframe.src.split('&name=')[0].split('&email=')[0];
      var pre = '';
      if (name)  pre += '&name='  + encodeURIComponent(name);
      if (email) pre += '&email=' + encodeURIComponent(email);
      iframe.src = src + pre;
    }

    // Confirmation banner above the calendar
    var old = document.getElementById('kx-booking-cue');
    if (old) old.remove();
    var cue = document.createElement('div');
    cue.id = 'kx-booking-cue';
    cue.innerHTML = '<strong>Thanks' + (name ? ', ' + name.split(' ')[0] : '') +
      '!</strong> Your message is in. Pick a time below and we’ll talk soon — your details are already filled in.';
    wrap.parentNode.insertBefore(cue, wrap);

    // Smooth scroll to the booking card
    setTimeout(function(){
      cue.scrollIntoView({ behavior:'smooth', block:'center' });
      wrap.classList.add('kx-cal-highlight');
      setTimeout(function(){ wrap.classList.remove('kx-cal-highlight'); }, 2400);
    }, 350);
  }, false);
})();
