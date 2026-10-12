(function () {
  'use strict';

  const LEGACY_COLUMNS = [
    'organization',
    'employer_type',
    'job_title',
    'job_area',
    'location',
    'location_area',
    'closing_date',
    'closing_time',
    'contract_type',
    'work_pattern',
    'salary',
    'apply_url',
    'job_reference',
    'date_checked',
    'source_url'
  ];
  const SUMMARY_COLUMNS = [...LEGACY_COLUMNS, 'job_summary'];

  function buildApplyUrlCounts(jobs) {
    const counts = new Map();

    jobs.forEach((job) => {
      const url = String(job.apply_url ?? '').trim();
      if (!url) {
        return;
      }
      counts.set(url, (counts.get(url) || 0) + 1);
    });

    return counts;
  }

  function getApplyLinkPresentation(job, applyUrlCounts) {
    const url = String(job.apply_url ?? '').trim();
    const isShared = Boolean(url) && (applyUrlCounts.get(url) || 0) > 1;
    const title = String(job.job_title ?? '').trim() || 'Untitled vacancy';
    const reference = String(job.job_reference ?? '').trim();

    return {
      isShared,
      label: isShared ? 'Open vacancies page' : 'View & Apply',
      ariaLabel: isShared
        ? `Open vacancies page: ${title}${reference ? `. Reference ${reference}` : ''}`
        : `View & Apply: ${title}`,
      reference: isShared ? reference : ''
    };
  }

  function escapeHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#39;');
  }

  function parseCsv(csvText) {
    const rows = [];
    let row = [];
    let field = '';
    let insideQuotes = false;

    for (let index = 0; index < csvText.length; index += 1) {
      const character = csvText[index];

      if (insideQuotes) {
        if (character === '"' && csvText[index + 1] === '"') {
          field += '"';
          index += 1;
        } else if (character === '"') {
          insideQuotes = false;
        } else {
          field += character;
        }
      } else if (character === '"' && field.length === 0) {
        insideQuotes = true;
      } else if (character === ',') {
        row.push(field);
        field = '';
      } else if (character === '\n') {
        row.push(field);
        rows.push(row);
        row = [];
        field = '';
      } else if (character !== '\r') {
        field += character;
      }
    }

    if (insideQuotes) {
      throw new Error('The vacancy file contains an unterminated quoted field.');
    }

    if (field.length > 0 || row.length > 0) {
      row.push(field);
      rows.push(row);
    }

    return rows.filter((candidate) => candidate.some((value) => value.trim() !== ''));
  }

  function sameColumns(actual, expected) {
    return actual.length === expected.length
      && actual.every((column, index) => column === expected[index]);
  }

  function recordsFromCsv(csvText) {
    const rows = parseCsv(csvText);
    if (rows.length === 0) {
      throw new Error('The vacancy file is empty.');
    }

    const headers = rows[0].map((header, index) => index === 0 ? header.replace(/^\uFEFF/, '') : header);
    const isLegacy = sameColumns(headers, LEGACY_COLUMNS);
    const isSummary = sameColumns(headers, SUMMARY_COLUMNS);

    if (!isLegacy && !isSummary) {
      throw new Error('The vacancy file does not match a supported 15- or 16-column contract.');
    }

    return rows.slice(1).map((values, rowIndex) => {
      if (values.length !== headers.length) {
        throw new Error(`Vacancy row ${rowIndex + 2} has ${values.length} fields; expected ${headers.length}.`);
      }

      const record = {};
      headers.forEach((column, index) => {
        record[column] = (values[index] ?? '').trim();
      });
      if (isLegacy) {
        record.job_summary = '';
      }
      return record;
    });
  }

  function jobMatchesKeyword(job, keyword) {
    const search = String(keyword ?? '').trim().toLocaleLowerCase('en-GB');
    if (!search) {
      return true;
    }
    const keywordFields = ['job_title', 'organization', 'job_area', 'location', 'location_area', 'job_summary'];
    return keywordFields.some((field) => String(job[field] ?? '').toLocaleLowerCase('en-GB').includes(search));
  }

  function renderSummaryMarkup(job) {
    const summary = String(job.job_summary ?? '').trim();
    if (!summary) {
      return '';
    }
    return `<p class="job-summary"><strong>What you'd do</strong><br>${escapeHtml(summary)}</p>`;
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
      LEGACY_COLUMNS,
      SUMMARY_COLUMNS,
      buildApplyUrlCounts,
      getApplyLinkPresentation,
      parseCsv,
      recordsFromCsv,
      jobMatchesKeyword,
      renderSummaryMarkup
    };
    return;
  }

  const state = {
    allJobs: [],
    currentJobs: [],
    applyUrlCounts: new Map(),
    londonNow: null,
    loaded: false
  };

  const elements = {
    main: document.querySelector('main'),
    controls: document.querySelector('#job-controls'),
    keyword: document.querySelector('#keyword-search'),
    jobArea: document.querySelector('#job-area-filter'),
    organisation: document.querySelector('#organisation-filter'),
    location: document.querySelector('#location-filter'),
    workPattern: document.querySelector('#work-pattern-filter'),
    filterButton: document.querySelector('#filter-button'),
    filterPanel: document.querySelector('#filter-panel'),
    filterCount: document.querySelector('#filter-count'),
    activeChips: document.querySelector('#active-chips'),
    clearFilters: document.querySelector('#clear-filters'),
    sort: document.querySelector('#sort-filter'),
    reset: document.querySelector('#reset-filters'),
    lastChecked: document.querySelector('#last-checked'),
    currentVacancies: document.querySelector('#current-vacancies'),
    resultsHeading: document.querySelector('#results-heading'),
    stateMessage: document.querySelector('#state-message'),
    jobList: document.querySelector('#job-list')
  };

  const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  function getLondonNow() {
    const parts = new Intl.DateTimeFormat('en-GB', {
      timeZone: 'Europe/London',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hourCycle: 'h23'
    }).formatToParts(new Date());

    const values = Object.fromEntries(parts
      .filter((part) => part.type !== 'literal')
      .map((part) => [part.type, Number(part.value)]));

    return {
      year: values.year,
      month: values.month,
      day: values.day,
      hour: values.hour,
      minute: values.minute,
      second: values.second,
      dateKey: `${values.year}-${String(values.month).padStart(2, '0')}-${String(values.day).padStart(2, '0')}`
    };
  }

  function isDateOnly(value) {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
    if (!match) {
      return false;
    }
    const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
    return date.getUTCFullYear() === Number(match[1])
      && date.getUTCMonth() === Number(match[2]) - 1
      && date.getUTCDate() === Number(match[3]);
  }

  function isTimeOnly(value) {
    if (value === '') {
      return true;
    }
    const match = /^(\d{2}):(\d{2})$/.exec(value);
    return Boolean(match) && Number(match[1]) <= 23 && Number(match[2]) <= 59;
  }

  function isExpired(job, londonNow) {
    if (!isDateOnly(job.closing_date) || !isTimeOnly(job.closing_time)) {
      return false;
    }

    if (job.closing_date < londonNow.dateKey) {
      return true;
    }

    if (job.closing_date > londonNow.dateKey || job.closing_time === '') {
      return false;
    }

    const [hours, minutes] = job.closing_time.split(':').map(Number);
    const nowMinutes = (londonNow.hour * 60) + londonNow.minute;
    return nowMinutes >= (hours * 60) + minutes;
  }

  function toDateParts(dateKey) {
    const [year, month, day] = dateKey.split('-').map(Number);
    return { year, month, day };
  }

  function dateDistanceInDays(fromDateKey, toDateKey) {
    const from = toDateParts(fromDateKey);
    const to = toDateParts(toDateKey);
    const fromUtc = Date.UTC(from.year, from.month - 1, from.day);
    const toUtc = Date.UTC(to.year, to.month - 1, to.day);
    return Math.round((toUtc - fromUtc) / 86400000);
  }

  function formatDate(dateKey) {
    if (!isDateOnly(dateKey)) {
      return 'Closing date not stated';
    }
    const { year, month, day } = toDateParts(dateKey);
    return `${day} ${MONTH_NAMES[month - 1]} ${year}`;
  }

  function formatClosingDate(job) {
    if (!isDateOnly(job.closing_date)) {
      return 'Closing date not stated';
    }
    const date = formatDate(job.closing_date);
    return job.closing_time && isTimeOnly(job.closing_time) ? `${date}, ${job.closing_time}` : date;
  }

  function urgencyLabel(job, londonNow) {
    if (!isDateOnly(job.closing_date)) {
      return '';
    }
    const distance = dateDistanceInDays(londonNow.dateKey, job.closing_date);
    if (distance === 0) {
      return 'Closes today';
    }
    if (distance === 1) {
      return 'Closes tomorrow';
    }
    if (distance >= 2 && distance <= 7) {
      return `Closes in ${distance} days`;
    }
    return '';
  }

  function newestDateChecked(jobs) {
    return jobs.reduce((latest, job) => {
      if (!isDateOnly(job.date_checked)) {
        return latest;
      }
      return !latest || job.date_checked > latest ? job.date_checked : latest;
    }, '');
  }

  function safeApplyUrl(value) {
    if (!String(value ?? '').trim()) {
      return '';
    }
    try {
      const url = new URL(value, window.location.href);
      return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : '';
    } catch {
      return '';
    }
  }

  function uniqueSorted(jobs, field) {
    return [...new Set(jobs.map((job) => job[field]).filter(Boolean))]
      .sort((left, right) => left.localeCompare(right, 'en-GB', { sensitivity: 'base' }));
  }

  function populateSelect(select, values) {
    const fragment = document.createDocumentFragment();
    values.forEach((value) => {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = value;
      fragment.append(option);
    });
    select.append(fragment);
  }

  function displayValue(value, fallback) {
    return value || fallback;
  }

  function renderJob(job) {
    const applyUrl = safeApplyUrl(job.apply_url);
    if (!applyUrl) {
      return '';
    }

    const location = displayValue(job.location || job.location_area, 'Location not stated');
    const salary = displayValue(job.salary, 'Salary not stated');
    const urgency = urgencyLabel(job, state.londonNow);
    const linkPresentation = getApplyLinkPresentation(job, state.applyUrlCounts);
    const summaryMarkup = renderSummaryMarkup(job);
    const referenceHint = linkPresentation.reference
      ? `<p class="job-reference">Reference: <span>${escapeHtml(linkPresentation.reference)}</span></p>`
      : '';
    const closingDateMarkup = isDateOnly(job.closing_date)
      ? `<time datetime="${escapeHtml(job.closing_date)}">${escapeHtml(formatClosingDate(job))}</time>`
      : `<span>${escapeHtml(formatClosingDate(job))}</span>`;

    return `<article class="job-row">
      <div class="job-main">
        <h3 class="job-title">${escapeHtml(displayValue(job.job_title, 'Untitled vacancy'))}</h3>
        <p class="job-org">${escapeHtml(displayValue(job.organization, 'Organisation not stated'))}</p>
        ${referenceHint}
        <div class="job-tags"><span class="tag">${escapeHtml(displayValue(job.job_area, 'Job area not stated'))}</span><span class="tag">${escapeHtml(displayValue(job.work_pattern, 'Work pattern not stated'))}</span></div>
        ${summaryMarkup}
      </div>
      <div class="job-facts">
        <div class="fact"><span class="fact-label">Location</span><span class="fact-value">${escapeHtml(location)}</span></div>
        <div class="fact"><span class="fact-label">Salary</span><span class="fact-value">${escapeHtml(salary)}</span></div>
        <div class="fact"><span class="fact-label">Closing</span><span class="fact-value">${urgency ? `<span class="urgency">${escapeHtml(urgency)}</span><br>` : ''}${closingDateMarkup}</span></div>
      </div>
      <div class="job-action">
        <a class="apply-button${linkPresentation.isShared ? ' secondary' : ''}" href="${escapeHtml(applyUrl)}" target="_blank" rel="noopener noreferrer" aria-label="${escapeHtml(linkPresentation.ariaLabel)}">${escapeHtml(linkPresentation.label)}</a>
        ${linkPresentation.isShared ? '<span class="apply-note">This employer uses a shared vacancies page.</span>' : ''}
      </div>
    </article>`;
  }

  function selectedFilters() {
    return {
      keyword: elements.keyword.value.trim().toLocaleLowerCase('en-GB'),
      jobArea: elements.jobArea.value,
      organisation: elements.organisation.value,
      location: elements.location.value,
      workPattern: elements.workPattern.value,
      sort: elements.sort.value
    };
  }

  function sortJobs(jobs, sort) {
    return [...jobs].sort((left, right) => {
      if (sort === 'organisation-az') {
        return left.organization.localeCompare(right.organization, 'en-GB', { sensitivity: 'base' })
          || left.job_title.localeCompare(right.job_title, 'en-GB', { sensitivity: 'base' });
      }
      if (sort === 'title-az') {
        return left.job_title.localeCompare(right.job_title, 'en-GB', { sensitivity: 'base' })
          || left.organization.localeCompare(right.organization, 'en-GB', { sensitivity: 'base' });
      }

      const leftHasDate = isDateOnly(left.closing_date);
      const rightHasDate = isDateOnly(right.closing_date);
      if (!leftHasDate && rightHasDate) {
        return 1;
      }
      if (leftHasDate && !rightHasDate) {
        return -1;
      }
      if (!leftHasDate && !rightHasDate) {
        return left.job_title.localeCompare(right.job_title, 'en-GB', { sensitivity: 'base' });
      }

      const leftTime = left.closing_time && isTimeOnly(left.closing_time) ? left.closing_time : '23:59';
      const rightTime = right.closing_time && isTimeOnly(right.closing_time) ? right.closing_time : '23:59';
      const leftDate = `${left.closing_date}T${leftTime}`;
      const rightDate = `${right.closing_date}T${rightTime}`;
      const closingOrder = leftDate.localeCompare(rightDate);
      if (sort === 'closing-latest') {
        return -closingOrder || left.job_title.localeCompare(right.job_title, 'en-GB', { sensitivity: 'base' });
      }
      return closingOrder || left.job_title.localeCompare(right.job_title, 'en-GB', { sensitivity: 'base' });
    });
  }

  function filteredJobs() {
    const filters = selectedFilters();
    const jobs = state.currentJobs.filter((job) => {
      const keywordMatches = jobMatchesKeyword(job, filters.keyword);
      const areaMatches = !filters.jobArea || job.job_area === filters.jobArea;
      const organisationMatches = !filters.organisation || job.organization === filters.organisation;
      const locationMatches = !filters.location || job.location_area === filters.location;
      const patternMatches = !filters.workPattern || job.work_pattern === filters.workPattern;
      return keywordMatches && areaMatches && organisationMatches && locationMatches && patternMatches;
    });
    return sortJobs(jobs, filters.sort);
  }

  function hasActiveFilters() {
    return Boolean(elements.keyword.value.trim() || elements.jobArea.value || elements.organisation.value || elements.location.value || elements.workPattern.value);
  }

  const filterDimensions = [
    ['jobArea', 'Job area'], ['location', 'Location'],
    ['workPattern', 'Work pattern'], ['organisation', 'Organisation']
  ];

  function renderFilterChips() {
    const active = filterDimensions.filter(([key]) => elements[key].value);
    elements.filterCount.textContent = String(active.length);
    elements.activeChips.innerHTML = active.map(([key, label]) =>
      `<span class="chip">${escapeHtml(label)}: ${escapeHtml(elements[key].value)}<button type="button" data-clear="${key}" aria-label="Remove ${escapeHtml(label)} filter">×</button></span>`
    ).join('');
  }

  function clearFilterDimensions() {
    filterDimensions.forEach(([key]) => { elements[key].value = ''; });
    render();
  }

  function setFilterPanelOpen(open) {
    elements.filterPanel.hidden = !open;
    elements.filterPanel.classList.toggle('is-open', open);
    elements.filterButton.setAttribute('aria-expanded', String(open));
  }

  function showState(title, description) {
    elements.stateMessage.hidden = false;
    elements.stateMessage.innerHTML = `<p class="state-message__title">${escapeHtml(title)}</p><p>${escapeHtml(description)}</p>`;
  }

  function hideState() {
    elements.stateMessage.hidden = true;
    elements.stateMessage.innerHTML = '';
  }

  function render() {
    if (!state.loaded) {
      return;
    }

    const jobs = filteredJobs();
    const active = hasActiveFilters();
    elements.resultsHeading.textContent = `${jobs.length} ${jobs.length === 1 ? 'job' : 'jobs'} found`;
    elements.reset.hidden = !active;
    renderFilterChips();
    elements.jobList.hidden = jobs.length === 0;

    if (jobs.length > 0) {
      hideState();
      elements.jobList.innerHTML = jobs.map(renderJob).join('');
      return;
    }

    elements.jobList.innerHTML = '';
    if (state.currentJobs.length === 0) {
      showState('There are currently no vacancies in the list.', 'Please check again after the next update.');
    } else {
      showState('No jobs match these choices', 'Try a broader keyword or clear one of the filters.');
    }
  }

  function resetFilters() {
    elements.keyword.value = '';
    elements.jobArea.value = '';
    elements.organisation.value = '';
    elements.location.value = '';
    elements.workPattern.value = '';
    elements.sort.value = 'closing-soonest';
    render();
    elements.keyword.focus();
  }

  function setControlsEnabled(enabled) {
    elements.controls.disabled = !enabled;
  }

  function loadOptions() {
    populateSelect(elements.jobArea, uniqueSorted(state.currentJobs, 'job_area'));
    populateSelect(elements.organisation, uniqueSorted(state.currentJobs, 'organization'));
    populateSelect(elements.location, uniqueSorted(state.currentJobs, 'location_area'));
    populateSelect(elements.workPattern, uniqueSorted(state.currentJobs, 'work_pattern'));
  }

  function visibleJobs(records, londonNow) {
    return records.filter((job) => !isExpired(job, londonNow)
      && safeApplyUrl(job.apply_url));
  }

  function loadSummary() {
    const latest = newestDateChecked(state.allJobs);
    elements.lastChecked.textContent = latest ? formatDate(latest) : '—';
    if (latest) {
      elements.lastChecked.dateTime = latest;
    }
    elements.currentVacancies.textContent = String(state.currentJobs.length);
  }

  function onLoaded(records) {
    state.londonNow = getLondonNow();
    state.allJobs = records.filter((job) => job.apply_url || job.job_title || job.organization);
    state.applyUrlCounts = buildApplyUrlCounts(state.allJobs);
    state.currentJobs = visibleJobs(state.allJobs, state.londonNow);
    state.loaded = true;
    loadSummary();
    loadOptions();
    setControlsEnabled(true);
    elements.main.setAttribute('aria-busy', 'false');
    render();
  }

  function refreshExpiryVisibility() {
    if (!state.loaded) {
      return;
    }

    const previousKeys = state.currentJobs.map((job) => job.job_reference || job.apply_url).join('|');
    state.londonNow = getLondonNow();
    const nextJobs = visibleJobs(state.allJobs, state.londonNow);
    const nextKeys = nextJobs.map((job) => job.job_reference || job.apply_url).join('|');

    if (previousKeys !== nextKeys) {
      state.currentJobs = nextJobs;
      loadSummary();
      render();
    }
  }

  function onLoadError() {
    elements.main.setAttribute('aria-busy', 'false');
    elements.resultsHeading.textContent = 'Job list unavailable';
    elements.currentVacancies.textContent = '—';
    elements.lastChecked.textContent = '—';
    elements.jobList.innerHTML = '';
    elements.jobList.hidden = true;
    showState('The job list is temporarily unavailable.', 'Please try again later.');
  }

  async function loadJobs() {
    try {
      const response = await fetch(`jobs.csv?updated=${Date.now()}`, { cache: 'no-store' });
      if (!response.ok) {
        throw new Error('The vacancy file could not be loaded.');
      }
      const csvText = await response.text();
      onLoaded(recordsFromCsv(csvText));
    } catch (error) {
      console.error(error);
      onLoadError();
    }
  }

  elements.keyword.addEventListener('input', render);
  [elements.jobArea, elements.organisation, elements.location, elements.workPattern, elements.sort]
    .forEach((control) => control.addEventListener('change', render));
  elements.reset.addEventListener('click', resetFilters);
  elements.clearFilters.addEventListener('click', clearFilterDimensions);
  elements.filterButton.addEventListener('click', () => setFilterPanelOpen(elements.filterPanel.hidden));
  elements.filterPanel.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      setFilterPanelOpen(false);
      elements.filterButton.focus();
    }
  });
  elements.activeChips.addEventListener('click', (event) => {
    const button = event.target.closest('button[data-clear]');
    if (button && filterDimensions.some(([key]) => key === button.dataset.clear)) {
      elements[button.dataset.clear].value = '';
      render();
      elements.filterButton.focus();
    }
  });

  loadJobs();
  window.setInterval(refreshExpiryVisibility, 60000);
}());
