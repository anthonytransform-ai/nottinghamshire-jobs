(function () {
  'use strict';

  const EXPECTED_COLUMNS = [
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

  const state = {
    allJobs: [],
    currentJobs: [],
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
    sort: document.querySelector('#sort-filter'),
    reset: document.querySelector('#reset-filters'),
    lastChecked: document.querySelector('#last-checked'),
    currentVacancies: document.querySelector('#current-vacancies'),
    resultsHeading: document.querySelector('#results-heading'),
    stateMessage: document.querySelector('#state-message'),
    jobList: document.querySelector('#job-list')
  };

  const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

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

    if (field.length > 0 || row.length > 0) {
      row.push(field);
      rows.push(row);
    }

    return rows.filter((candidate) => candidate.some((value) => value.trim() !== ''));
  }

  function recordsFromCsv(csvText) {
    const rows = parseCsv(csvText);
    if (rows.length === 0) {
      throw new Error('The vacancy file is empty.');
    }

    const headers = rows[0].map((header, index) => index === 0 ? header.replace(/^\uFEFF/, '') : header);
    const matchesContract = headers.length === EXPECTED_COLUMNS.length
      && headers.every((header, index) => header === EXPECTED_COLUMNS[index]);

    if (!matchesContract) {
      throw new Error('The vacancy file does not match the expected column contract.');
    }

    return rows.slice(1).map((values) => {
      const record = {};
      EXPECTED_COLUMNS.forEach((column, index) => {
        record[column] = (values[index] ?? '').trim();
      });
      return record;
    });
  }

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
    const date = formatDate(job.closing_date);
    return job.closing_time ? `${date}, ${job.closing_time}` : date;
  }

  function urgencyLabel(job, londonNow) {
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
    if (!value.trim()) {
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

  function icon(name) {
    if (name === 'location') {
      return '<svg class="job-row__icon" aria-hidden="true" viewBox="0 0 24 24" focusable="false"><path d="M12 21s7-6.05 7-12a7 7 0 1 0-14 0c0 5.95 7 12 7 12Z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"></path><circle cx="12" cy="9" r="2.25" fill="none" stroke="currentColor" stroke-width="2"></circle></svg>';
    }
    return '<svg class="job-area__icon" aria-hidden="true" viewBox="0 0 24 24" focusable="false"><path d="M4 8.5h16v11H4z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"></path><path d="M8 8.5V6.75A1.75 1.75 0 0 1 9.75 5h4.5A1.75 1.75 0 0 1 16 6.75V8.5M4 13h16M10 13v1.5h4V13" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"></path></svg>';
  }

  function displayValue(value, fallback) {
    return value || fallback;
  }

  function renderJob(job) {
    const applyUrl = safeApplyUrl(job.apply_url);
    if (!applyUrl) {
      return '';
    }

    const contract = [job.work_pattern, job.contract_type].filter(Boolean).join(' · ') || 'Work pattern not stated';
    const location = displayValue(job.location || job.location_area, 'Location not stated');
    const salary = displayValue(job.salary, 'Salary not stated');
    const urgency = urgencyLabel(job, state.londonNow);

    return `<article class="job-row">
      <div class="job-row__primary">
        <h3 class="job-title">${escapeHtml(displayValue(job.job_title, 'Untitled vacancy'))}</h3>
        <p class="job-organization">${escapeHtml(displayValue(job.organization, 'Organisation not stated'))}</p>
        <p class="job-area">${icon('briefcase')}<span>${escapeHtml(displayValue(job.job_area, 'Job area not stated'))}</span></p>
      </div>
      <div class="job-row__location-group">
        <div class="job-row__location">${icon('location')}<span>${escapeHtml(location)}</span></div>
        <div class="job-row__contract"><span>${escapeHtml(contract)}</span></div>
      </div>
      <div class="job-row__salary">${escapeHtml(salary)}</div>
      <div class="job-row__deadline">${urgency ? `<span class="job-row__urgency">${escapeHtml(urgency)}</span>` : ''}<time class="job-row__date" datetime="${escapeHtml(job.closing_date)}">${escapeHtml(formatClosingDate(job))}</time></div>
      <a class="job-apply" href="${escapeHtml(applyUrl)}" target="_blank" rel="noopener noreferrer" aria-label="View &amp; Apply: ${escapeHtml(displayValue(job.job_title, 'Untitled vacancy'))}">View &amp; Apply</a>
    </article>`;
  }

  function selectedFilters() {
    return {
      keyword: elements.keyword.value.trim().toLocaleLowerCase('en-GB'),
      jobArea: elements.jobArea.value,
      organisation: elements.organisation.value,
      location: elements.location.value,
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

      const leftDate = `${left.closing_date}T${left.closing_time || '23:59'}`;
      const rightDate = `${right.closing_date}T${right.closing_time || '23:59'}`;
      const closingOrder = leftDate.localeCompare(rightDate);
      if (sort === 'closing-latest') {
        return -closingOrder || left.job_title.localeCompare(right.job_title, 'en-GB', { sensitivity: 'base' });
      }
      return closingOrder || left.job_title.localeCompare(right.job_title, 'en-GB', { sensitivity: 'base' });
    });
  }

  function filteredJobs() {
    const filters = selectedFilters();
    const keywordFields = ['job_title', 'organization', 'job_area', 'location', 'location_area'];
    const jobs = state.currentJobs.filter((job) => {
      const keywordMatches = !filters.keyword || keywordFields.some((field) => job[field].toLocaleLowerCase('en-GB').includes(filters.keyword));
      const areaMatches = !filters.jobArea || job.job_area === filters.jobArea;
      const organisationMatches = !filters.organisation || job.organization === filters.organisation;
      const locationMatches = !filters.location || job.location_area === filters.location;
      return keywordMatches && areaMatches && organisationMatches && locationMatches;
    });
    return sortJobs(jobs, filters.sort);
  }

  function hasActiveFilters() {
    return Boolean(elements.keyword.value.trim() || elements.jobArea.value || elements.organisation.value || elements.location.value);
  }

  function showState(title, description, includeReset) {
    elements.stateMessage.hidden = false;
    elements.stateMessage.innerHTML = `<p class="state-message__title">${escapeHtml(title)}</p><p>${escapeHtml(description)}</p>${includeReset ? '<button class="reset-button state-reset" type="button">Reset filters</button>' : ''}`;
    const stateReset = elements.stateMessage.querySelector('.state-reset');
    if (stateReset) {
      stateReset.addEventListener('click', resetFilters);
    }
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

    if (jobs.length > 0) {
      hideState();
      elements.jobList.innerHTML = jobs.map(renderJob).join('');
      return;
    }

    elements.jobList.innerHTML = '';
    if (state.currentJobs.length === 0) {
      showState('There are currently no vacancies in the list.', 'Please check again after the next update.', false);
    } else {
      showState('No jobs match these filters.', 'Try changing or clearing one of your filters.', active);
    }
  }

  function resetFilters() {
    elements.keyword.value = '';
    elements.jobArea.value = '';
    elements.organisation.value = '';
    elements.location.value = '';
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
  }

  function visibleJobs(records, londonNow) {
    return records.filter((job) => isDateOnly(job.closing_date)
      && !isExpired(job, londonNow)
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
    showState('The job list is temporarily unavailable.', 'Please try again later.', false);
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
  [elements.jobArea, elements.organisation, elements.location, elements.sort]
    .forEach((control) => control.addEventListener('change', render));
  elements.reset.addEventListener('click', resetFilters);

  loadJobs();
  window.setInterval(refreshExpiryVisibility, 60000);
}());
