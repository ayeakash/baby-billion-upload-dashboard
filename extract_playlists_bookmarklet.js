/**
 * Browser Console Script - Extract Playlists & Categories from CMS
 *
 * Instructions:
 * 1. Open https://cms-v1.d148rwrq639wa8.amplifyapp.com/dashboard/cms/playlists in your browser
 * 2. Open Developer Tools (F12 or Ctrl+Shift+I)
 * 3. Go to Console tab
 * 4. Paste this entire script and press Enter
 * 5. Follow the prompts
 */

(async function extractPlaylists() {
  console.log('Starting playlist extraction...');

  const playlists = [];

  // Get all playlist rows/items from the page
  // Try multiple selectors for different table structures
  let rows = document.querySelectorAll('tbody tr, [role="row"]');

  if (rows.length === 0) {
    // Try div-based layout
    rows = document.querySelectorAll('[class*="item"], [class*="row"], [class*="playlist"]');
  }

  console.log(`Found ${rows.length} potential rows`);

  // Extract playlist info from each row
  for (let row of rows) {
    try {
      // Get text content from row
      const text = row.textContent;

      // Find title (usually in first cell or column)
      const cells = row.querySelectorAll('td, [role="gridcell"]');
      if (cells.length === 0) continue;

      const title = cells[0]?.textContent?.trim();
      if (!title || title.length < 2) continue;

      // Look for edit link/button
      const editLink = row.querySelector('a[href*="edit"], button[data-id], [class*="edit"]');
      const editUrl = editLink?.href || editLink?.getAttribute('data-url') || '';

      const playlist = {
        id: title.toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, ''),
        title: title,
        editUrl: editUrl,
        categories: []
      };

      // Check if playlist already exists
      if (!playlists.find(p => p.title === title)) {
        playlists.push(playlist);
        console.log(`Added: ${title}`);
      }
    } catch (e) {
      console.debug('Error processing row:', e);
    }
  }

  console.log(`\n=== Found ${playlists.length} playlists ===\n`);

  if (playlists.length === 0) {
    console.warn('No playlists found. Check if the page loaded correctly.');
    console.log('Page structure:', document.body.innerHTML.substring(0, 500));
    return;
  }

  // Now fetch categories for each playlist
  console.log('Fetching categories for each playlist...\n');

  for (let i = 0; i < playlists.length; i++) {
    const playlist = playlists[i];
    console.log(`[${i+1}/${playlists.length}] Processing: ${playlist.title}`);

    if (playlist.editUrl) {
      try {
        // Navigate to edit page
        const editPage = window.open(playlist.editUrl, '_blank');

        // Wait a bit for page to load
        await new Promise(resolve => setTimeout(resolve, 3000));

        // Extract categories from edit page
        const categories = extractCategoriesFromEditPage(editPage);
        playlist.categories = categories;

        console.log(`  Found ${categories.length} categories`);

        // Close the edit page
        editPage.close();

      } catch (e) {
        console.warn(`  Failed to fetch categories: ${e.message}`);
      }
    }
  }

  // Prepare data for export
  const exportData = {
    timestamp: new Date().toISOString(),
    totalPlaylists: playlists.length,
    totalCategories: playlists.reduce((sum, p) => sum + p.categories.length, 0),
    playlists: playlists.map(p => ({
      id: p.id,
      title: p.title,
      categories: p.categories.map(c => ({
        id: c.id,
        title: c.title
      }))
    }))
  };

  // Display results
  console.log('\n=== EXTRACTION COMPLETE ===\n');
  console.log(JSON.stringify(exportData, null, 2));

  // Copy to clipboard
  try {
    await navigator.clipboard.writeText(JSON.stringify(exportData, null, 2));
    console.log('\n✓ Data copied to clipboard!');
  } catch (e) {
    console.log('\n(Could not copy to clipboard, but data is logged above)');
  }

  // Return for further processing
  return exportData;
})();

function extractCategoriesFromEditPage(page) {
  try {
    // Wait for page to be accessible
    const checkInterval = setInterval(() => {
      if (!page || page.closed) {
        clearInterval(checkInterval);
        return [];
      }
    }, 100);

    // Try to find categories in the edit page
    const categories = [];

    // Look for checkboxes
    const checkboxes = page.document.querySelectorAll('input[type="checkbox"]');
    for (let checkbox of checkboxes) {
      const label = checkbox.parentElement?.textContent || checkbox.getAttribute('title') || '';
      if (label && label.length > 2 && label.length < 100) {
        categories.push({
          id: checkbox.value || label.toLowerCase().replace(/\s+/g, '-'),
          title: label.trim()
        });
      }
    }

    // Look for select options
    const selects = page.document.querySelectorAll('select');
    for (let select of selects) {
      const options = select.querySelectorAll('option');
      for (let option of options) {
        const text = option.textContent?.trim();
        if (text && !['select', 'choose', 'none', ''].includes(text.toLowerCase())) {
          categories.push({
            id: option.value || text.toLowerCase().replace(/\s+/g, '-'),
            title: text
          });
        }
      }
    }

    // Deduplicate
    const seen = new Set();
    return categories.filter(cat => {
      const key = cat.title.toLowerCase();
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });

  } catch (e) {
    console.warn('Error extracting categories:', e);
    return [];
  }
}
