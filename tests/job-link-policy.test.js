const test = require('node:test');
const assert = require('node:assert/strict');

const {
  buildApplyUrlCounts,
  getApplyLinkPresentation
} = require('../app.js');

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
