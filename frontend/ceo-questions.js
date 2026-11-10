/* ===== CEO questions — clickable multiple-choice cards =====
 *
 * Agents ask with the ask_ceo tool. Their message contains readable text and
 * a ```omc-questions {json}``` block; this module replaces the block with a
 * card. Submitting sends the answer as a normal CEO message through the
 * callback, so it resolves the waiting task like a typed reply.
 */
(function () {
  const FENCE = /```omc-questions\s*\n([\s\S]*?)\n```/;
  const t = (s) => (window.I18N && I18N.t ? I18N.t(s) : s);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  /** {text, questions} if the message carries questions, else null. */
  function extract(text) {
    const m = FENCE.exec(text || '');
    if (!m) return null;
    try {
      const data = JSON.parse(m[1]);
      const questions = Array.isArray(data.questions) ? data.questions : [];
      if (!questions.length) return null;
      // The readable list duplicates the card: keep only the context lines.
      const before = (text.slice(0, m.index) || '').split('\n');
      const firstQ = before.findIndex((l) => /^1\.\s/.test(l));
      const intro = (firstQ >= 0 ? before.slice(0, firstQ) : before).join('\n').trim();
      return { text: intro, questions };
    } catch (e) {
      console.warn('[ceo-questions] bad block', e);
      return null;
    }
  }

  function buildAnswer(questions, picks, others) {
    const lines = [t('My answers:')];
    questions.forEach((q, i) => {
      const chosen = [...picks[i]];
      const other = (others[i] || '').trim();
      if (other) chosen.push(other);
      const label = q.header || q.question;
      lines.push(`${i + 1}. ${label} → ${chosen.join(', ') || t('(no answer)')}`);
    });
    return lines.join('\n');
  }

  /** Render the card. onSubmit(answerText). answered = already replied. */
  function render(questions, onSubmit, answered) {
    const card = document.createElement('div');
    card.className = 'ceo-q-card' + (answered ? ' answered' : '');
    // Agent-written labels stay as written; UI strings are translated with t().
    card.setAttribute('data-no-i18n', '');
    const picks = questions.map(() => new Set());
    const others = questions.map(() => '');

    questions.forEach((q, qi) => {
      const block = document.createElement('div');
      block.className = 'ceo-q-block';
      block.innerHTML = `
        ${q.header ? `<span class="ceo-q-header">${esc(q.header)}</span>` : ''}
        <div class="ceo-q-question">${esc(q.question)}</div>
        <div class="ceo-q-hint">${esc(q.multi_select ? t('Several choices possible') : t('One choice'))}</div>`;
      const opts = document.createElement('div');
      opts.className = 'ceo-q-options';
      (q.options || []).forEach((o) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'ceo-q-option';
        btn.innerHTML = `<span class="ceo-q-label">${esc(o.label)}${o.recommended
          ? ` <span class="ceo-q-reco">${esc(t('Recommended'))}</span>` : ''}</span>`
          + (o.description ? `<span class="ceo-q-desc">${esc(o.description)}</span>` : '');
        btn.disabled = !!answered;
        btn.addEventListener('click', () => {
          if (!q.multi_select) {
            picks[qi].clear();
            opts.querySelectorAll('.ceo-q-option').forEach((b) => b.classList.remove('selected'));
          }
          if (picks[qi].has(o.label)) { picks[qi].delete(o.label); btn.classList.remove('selected'); }
          else { picks[qi].add(o.label); btn.classList.add('selected'); }
          update();
        });
        opts.appendChild(btn);
      });
      block.appendChild(opts);
      const other = document.createElement('input');
      other.type = 'text';
      other.className = 'ceo-q-other';
      other.placeholder = t('Other answer or note (optional)');
      other.disabled = !!answered;
      other.addEventListener('input', () => {
        others[qi] = other.value;
        if (!q.multi_select && other.value.trim()) {
          picks[qi].clear();
          opts.querySelectorAll('.ceo-q-option').forEach((b) => b.classList.remove('selected'));
        }
        update();
      });
      block.appendChild(other);
      card.appendChild(block);
    });

    const submit = document.createElement('button');
    submit.type = 'button';
    submit.className = 'pixel-btn small ceo-q-submit';
    submit.textContent = answered ? t('Answered') : t('Send answers');
    submit.disabled = true;
    function update() {
      if (answered) return;
      submit.disabled = !questions.every((q, i) => picks[i].size || (others[i] || '').trim());
    }
    submit.addEventListener('click', () => {
      if (submit.disabled) return;
      const text = buildAnswer(questions, picks, others);
      card.classList.add('answered');
      card.querySelectorAll('button, input').forEach((el) => { el.disabled = true; });
      submit.textContent = t('Answered');
      onSubmit && onSubmit(text);
    });
    card.appendChild(submit);
    return card;
  }

  window.OmcQuestions = { extract, render, buildAnswer };
})();
