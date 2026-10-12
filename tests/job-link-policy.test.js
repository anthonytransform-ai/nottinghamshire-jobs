const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const {
  LEGACY_COLUMNS,
  SUMMARY_COLUMNS,
  buildApplyUrlCounts,
  getApplyLinkPresentation,
  recordsFromCsv,
  jobMatchesKeyword,
  renderSummaryMarkup
} = require('../app.js');

function csvLine(values) {
  return values.map((value) => {
    const text = String(value ?? '');
    if (/[",\r\n]/.test(text)) {
      return `"${text.replaceAll('"', '""')}"`;
    }
    return text;
  }).join(',');
}

function csvFor(columns, row) {
  return `${csvLine(columns)}\r\n${csvLine(columns.map((column) => row[column] ?? ''))}\r\n`;
}

const baseRow = {
  organization: 'Example Council',
  employer_type: 'Council',
  job_title: 'Administrator',
  job_area: 'Administration & Business Support',
  location: 'Nottingham',
  location_area: 'Nottingham',
  closing_date: '2026-10-10',
  closing_time: '17:00',
  contract_type: 'Permanent',
  work_pattern: 'Full-time',
  salary: '£25,000',
  apply_url: 'https://example.org/jobs/1',
  job_reference: 'REF-1',
  date_checked: '2026-09-27',
  source_url: 'https://example.org/jobs/1',
  job_summary: 'Coordinate records, respond to enquiries and support the team with day-to-day administration.'
};

test('legacy 15-column feed parses and supplies a blank job_summary', () => {
  const [record] = recordsFromCsv(csvFor(LEGACY_COLUMNS, baseRow));
  assert.equal(record.job_title, 'Administrator');
  assert.equal(record.job_summary, '');
});

test('new 16-column feed parses job_summary including commas and quotes', () => {
  const row = {
    ...baseRow,
    job_summary: 'Coordinate records, answer calls and support the "first response" process.'
  };
  const [record] = recordsFromCsv(csvFor(SUMMARY_COLUMNS, row));
  assert.equal(record.job_summary, row.job_summary);
});

test('unsupported or malformed schemas fail closed', () => {
  const wrongColumns = [...LEGACY_COLUMNS.slice(0, -1), 'job_summary'];
  assert.throws(() => recordsFromCsv(csvFor(wrongColumns, baseRow)), /supported 15- or 16-column contract/);
  assert.throws(() => recordsFromCsv(`${csvLine(SUMMARY_COLUMNS)}\r\nonly,three,fields\r\n`), /has 3 fields/);
});

test('summary text is included in keyword matching', () => {
  assert.equal(jobMatchesKeyword(baseRow, 'day-to-day administration'), true);
  assert.equal(jobMatchesKeyword(baseRow, 'clinical theatre'), false);
});

test('summary markup is rendered only when a summary is present', () => {
  const present = renderSummaryMarkup(baseRow);
  assert.match(present, /What you'd do/);
  assert.match(present, /Coordinate records/);
  assert.equal(renderSummaryMarkup({ ...baseRow, job_summary: '' }), '');
});

test('summary markup escapes source text before rendering', () => {
  const markup = renderSummaryMarkup({ ...baseRow, job_summary: '<script>alert("x")</script>' });
  assert.doesNotMatch(markup, /<script>/);
  assert.match(markup, /&lt;script&gt;/);
});

test('shared application URLs are identified without collapsing distinct jobs', () => {
  const sharedUrl = 'https://example.org/vacancies';
  const jobs = [
    {
      job_title: 'Administrator',
      job_reference: 'REF-100',
      apply_url: sharedUrl
    },
    {
      job_title: 'Planner',
      job_reference: 'REF-200',
      apply_url: sharedUrl
    }
  ];

  const counts = buildApplyUrlCounts(jobs);
  assert.equal(counts.get(sharedUrl), 2);

  const first = getApplyLinkPresentation(jobs[0], counts);
  const second = getApplyLinkPresentation(jobs[1], counts);

  assert.equal(first.isShared, true);
  assert.equal(first.label, 'Open vacancies page');
  assert.equal(first.reference, 'REF-100');
  assert.match(first.ariaLabel, /Administrator/);
  assert.match(first.ariaLabel, /REF-100/);

  assert.equal(second.isShared, true);
  assert.equal(second.label, 'Open vacancies page');
  assert.match(second.ariaLabel, /Planner/);
});

test('shared pages do not invent a reference when the source has none', () => {
  const sharedUrl = 'https://example.org/vacancies';
  const jobs = [
    { job_title: 'Caretaker', job_reference: '', apply_url: sharedUrl },
    { job_title: 'Receptionist', job_reference: '', apply_url: sharedUrl }
  ];

  const presentation = getApplyLinkPresentation(jobs[0], buildApplyUrlCounts(jobs));

  assert.equal(presentation.isShared, true);
  assert.equal(presentation.label, 'Open vacancies page');
  assert.equal(presentation.reference, '');
  assert.equal(presentation.ariaLabel, 'Open vacancies page: Caretaker');
});

test('unique application URLs keep the existing View & Apply action', () => {
  const job = {
    job_title: 'Support Worker',
    job_reference: 'REF-300',
    apply_url: 'https://example.org/jobs/300'
  };

  const presentation = getApplyLinkPresentation(job, buildApplyUrlCounts([job]));

  assert.equal(presentation.isShared, false);
  assert.equal(presentation.label, 'View & Apply');
  assert.equal(presentation.reference, '');
  assert.equal(presentation.ariaLabel, 'View & Apply: Support Worker');
});

// Exercise the production controller and event handlers without a runtime dependency.
// Rendered layout, native controls and focus are also checked in a real browser.
async function siteHarness(rows, { fail = false } = {}) {
  const ids = ['job-controls', 'keyword-search', 'job-area-filter', 'organisation-filter',
    'location-filter', 'work-pattern-filter', 'filter-button', 'filter-panel',
    'filter-count', 'active-chips', 'clear-filters', 'sort-filter', 'reset-filters',
    'last-checked', 'current-vacancies', 'results-heading', 'state-message', 'job-list'];
  let focused = null;
  function element() {
    const classes = new Set();
    return {
      value: '', innerHTML: '', textContent: '', hidden: false, disabled: false,
      children: [], listeners: {}, attributes: {},
      classList: { toggle(name, on) { if (on) classes.add(name); else classes.delete(name); } },
      addEventListener(type, handler) { this.listeners[type] = handler; },
      setAttribute(name, value) { this.attributes[name] = value; },
      append(child) { this.children.push(child); },
      focus() { focused = this; }
    };
  }
  const elements = Object.fromEntries(ids.map(id => [id, element()]));
  elements['sort-filter'].value = 'closing-soonest';
  elements['filter-panel'].hidden = true;
  elements['job-controls'].disabled = true;
  const main = element();
  main.attributes['aria-busy'] = 'true';
  let now = new Date('2026-10-13T10:00:00Z'); // 11:00 Europe/London.
  class ClockDate extends Date {
    constructor(...args) { super(...(args.length ? args : [now])); }
    static now() { return now.getTime(); }
  }
  let refresh;
  const errors = [];
  const csv = `${csvLine(SUMMARY_COLUMNS)}\n${rows.map(row => csvLine(SUMMARY_COLUMNS.map(key => row[key] ?? ''))).join('\n')}\n`;
  vm.runInNewContext(fs.readFileSync(require.resolve('../app.js'), 'utf8'), {
    Date: ClockDate, Intl, URL,
    document: {
      querySelector: selector => selector === 'main' ? main : elements[selector.slice(1)],
      createDocumentFragment: element, createElement: element
    },
    window: { location: { href: 'https://example.org/' }, setInterval(fn) { refresh = fn; } },
    fetch: async () => ({ ok: !fail, text: async () => csv }),
    console: { error: error => errors.push(error.message) }
  });
  await new Promise(resolve => setImmediate(resolve));
  return {
    elements, main, errors,
    set(id, value, event = 'change') {
      elements[id].value = value;
      elements[id].listeners[event]({ target: elements[id] });
    },
    click(id, event = {}) { elements[id].listeners.click(event); },
    titles() { return [...elements['job-list'].innerHTML.matchAll(/<h3 class="job-title">(.*?)<\/h3>/g)].map(match => match[1]); },
    advance(time) { now = new Date(time); refresh(); },
    focused: () => focused
  };
}

const interactionRows = [
  { ...baseRow, job_title: 'Zebra Administrator', organization: 'Alpha Council', closing_date: '2026-10-15', work_pattern: 'Part-time', apply_url: 'https://example.org/shared' },
  { ...baseRow, job_title: 'Alpha Technician', organization: 'Beta Trust', closing_date: '2026-10-20', job_area: 'IT & Digital', location_area: 'Gedling', work_pattern: 'Full-time', apply_url: 'https://example.org/technician' },
  { ...baseRow, job_title: 'Undated Officer', organization: 'Gamma Council', closing_date: '', closing_time: '', apply_url: 'https://example.org/shared' },
  { ...baseRow, job_title: 'School Assistant', organization: 'Delta School', closing_date: '2026-10-13', closing_time: '12:00', job_area: 'Education & Training', work_pattern: 'Part-time', apply_url: 'https://example.org/school' },
  { ...baseRow, job_title: 'Expired vacancy', closing_date: '2026-10-12' },
  { ...baseRow, job_title: 'Unsafe vacancy', closing_date: '', apply_url: 'javascript:alert(1)' }
];

test('production load preserves expiry, safe links, freshness and shared-page presentation', async () => {
  const site = await siteHarness(interactionRows);
  assert.deepEqual(site.titles(), ['School Assistant', 'Zebra Administrator', 'Alpha Technician', 'Undated Officer']);
  assert.equal(site.elements['current-vacancies'].textContent, '4');
  assert.equal(site.elements['last-checked'].textContent, '27 Sep 2026');
  assert.equal(site.main.attributes['aria-busy'], 'false');
  assert.equal(site.elements['job-controls'].disabled, false);
  assert.match(site.elements['job-list'].innerHTML, /Open vacancies page/);
  assert.match(site.elements['job-list'].innerHTML, /This employer uses a shared vacancies page/);
  assert.match(site.elements['job-list'].innerHTML, /Reference: <span>REF-1/);
  assert.match(site.elements['job-list'].innerHTML, /target="_blank" rel="noopener noreferrer"/);
  assert.equal(site.errors.length, 0);
});

test('filter disclosure opens, closes and Escape returns keyboard focus', async () => {
  const site = await siteHarness(interactionRows);
  site.click('filter-button');
  assert.equal(site.elements['filter-panel'].hidden, false);
  assert.equal(site.elements['filter-button'].attributes['aria-expanded'], 'true');
  site.click('filter-button');
  assert.equal(site.elements['filter-panel'].hidden, true);
  site.click('filter-button');
  site.elements['filter-panel'].listeners.keydown({ key: 'Escape' });
  assert.equal(site.elements['filter-panel'].hidden, true);
  assert.equal(site.focused(), site.elements['filter-button']);
});

for (const [id, value, titles] of [
  ['job-area-filter', 'IT & Digital', ['Alpha Technician']],
  ['location-filter', 'Gedling', ['Alpha Technician']],
  ['work-pattern-filter', 'Part-time', ['School Assistant', 'Zebra Administrator']],
  ['organisation-filter', 'Gamma Council', ['Undated Officer']]
]) {
  test(`production ${id} filters rows, populates its options and emits a chip`, async () => {
    const site = await siteHarness(interactionRows);
    assert.ok(site.elements[id].children[0].children.some(option => option.value === value));
    site.set(id, value);
    assert.deepEqual(site.titles(), titles);
    assert.equal(site.elements['filter-count'].textContent, '1');
    assert.match(site.elements['active-chips'].innerHTML, /aria-label="Remove /);
  });
}

test('chip removal clears only its dimension and preserves search and remaining filter', async () => {
  const site = await siteHarness(interactionRows);
  site.set('keyword-search', 'Administrator', 'input');
  site.set('work-pattern-filter', 'Part-time');
  site.set('location-filter', 'Nottingham');
  site.click('active-chips', { target: { closest: () => ({ dataset: { clear: 'workPattern' } }) } });
  assert.equal(site.elements['work-pattern-filter'].value, '');
  assert.equal(site.elements['location-filter'].value, 'Nottingham');
  assert.equal(site.elements['keyword-search'].value, 'Administrator');
  assert.equal(site.elements['filter-count'].textContent, '1');
  assert.deepEqual(site.titles(), ['Zebra Administrator']);
  assert.equal(site.focused(), site.elements['filter-button']);
});

test('zero results -> Clear filters restores the same list node, preserving query and sort', async () => {
  const site = await siteHarness(interactionRows);
  const list = site.elements['job-list'];
  site.set('keyword-search', 'Administrator', 'input');
  site.set('sort-filter', 'title-az');
  site.set('job-area-filter', 'Education & Training');
  assert.deepEqual(site.titles(), []);
  assert.equal(list.hidden, true);
  assert.match(site.elements['state-message'].innerHTML, /No jobs match these choices/);
  site.click('clear-filters');
  assert.equal(site.elements['job-list'], list);
  assert.equal(list.hidden, false);
  assert.deepEqual(site.titles(), ['Zebra Administrator']);
  assert.equal(site.elements['keyword-search'].value, 'Administrator');
  assert.equal(site.elements['sort-filter'].value, 'title-az');
  assert.equal(site.elements['state-message'].hidden, true);
  assert.equal(site.elements['filter-count'].textContent, '0');
});

test('zero results -> Reset search & filters restores all jobs and Closing soonest', async () => {
  const site = await siteHarness(interactionRows);
  site.set('keyword-search', 'no such vacancy', 'input');
  site.set('work-pattern-filter', 'Full-time');
  site.set('sort-filter', 'closing-latest');
  site.click('reset-filters');
  assert.equal(site.elements['keyword-search'].value, '');
  assert.equal(site.elements['work-pattern-filter'].value, '');
  assert.equal(site.elements['sort-filter'].value, 'closing-soonest');
  assert.equal(site.elements['reset-filters'].hidden, true);
  assert.equal(site.elements['active-chips'].innerHTML, '');
  assert.deepEqual(site.titles(), ['School Assistant', 'Zebra Administrator', 'Alpha Technician', 'Undated Officer']);
  assert.equal(site.focused(), site.elements['keyword-search']);
});

test('all alternate sort modes preserve existing order and keep undated jobs after dated jobs', async () => {
  const site = await siteHarness(interactionRows);
  for (const [sort, titles] of [
    ['organisation-az', ['Zebra Administrator', 'Alpha Technician', 'School Assistant', 'Undated Officer']],
    ['title-az', ['Alpha Technician', 'School Assistant', 'Undated Officer', 'Zebra Administrator']],
    ['closing-latest', ['Alpha Technician', 'Zebra Administrator', 'School Assistant', 'Undated Officer']]
  ]) {
    site.set('sort-filter', sort);
    assert.deepEqual(site.titles(), titles);
  }
});

test('minute refresh expires a vacancy at its Europe/London deadline', async () => {
  const site = await siteHarness(interactionRows);
  site.advance('2026-10-13T11:00:00Z'); // 12:00 Europe/London.
  assert.deepEqual(site.titles(), ['Zebra Administrator', 'Alpha Technician', 'Undated Officer']);
  assert.equal(site.elements['current-vacancies'].textContent, '3');
});

test('empty feed and failed fetch expose honest states without enabling failed-load controls', async () => {
  const empty = await siteHarness([]);
  assert.equal(empty.elements['current-vacancies'].textContent, '0');
  assert.match(empty.elements['state-message'].innerHTML, /currently no vacancies/);
  const failed = await siteHarness(interactionRows, { fail: true });
  assert.equal(failed.elements['job-controls'].disabled, true);
  assert.equal(failed.main.attributes['aria-busy'], 'false');
  assert.match(failed.elements['state-message'].innerHTML, /temporarily unavailable/);
  assert.equal(failed.errors.length, 1);
});
