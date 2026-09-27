const test = require('node:test');
const assert = require('node:assert/strict');

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
