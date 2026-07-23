/*
 * Open popup on map.
 *
 * Does not require JQuery.
 */
function popupChurch(markerName){
    document.getElementById("map-iframe").contentWindow[markerName].openPopup();
}

/*
 * Handles place auto-completion.
 *
 * Requires JQuery UI autocomplete.
 *
 * https://jqueryui.com/autocomplete/#remote-with-cache
 * https://jqueryui.com/autocomplete/#custom-data
 * https://api.jqueryui.com/autocomplete/
 *
 * Adresse API documentation
 * https://adresse.data.gouv.fr/api-doc/adresse
 */
$( function() {
    let autocompleteUrl = $('#search-input').attr('data-autocomplete-url');
    let autocompleteHitsUrl = $('#search-input').attr('data-autocomplete-hits-url');
    let latitude = $('#search-input').attr('data-autocomplete-latitude') || '';
    let longitude = $('#search-input').attr('data-autocomplete-longitude') || '';

    let cache = {};
    $( "#search-input" ).autocomplete({
      minLength: 3,
      source: function( request, response ) {
        let term = request.term;
        if (term in cache) {
          response(cache[term]);
          return;
        }

        $.getJSON( autocompleteUrl, {
          query: request.term,
          latitude: latitude,
          longitude: longitude,
        }, function( data, status, xhr ) {
          let optionList = [];
          data.forEach((obj, idx) => {
            obj._rank = idx;
            obj._query = term;
            optionList.push(obj);
          });
          cache[term] = optionList;
          response(optionList);
        });
      },
      open: function() {
        $("ul.ui-menu").width( $(this).innerWidth());
      },
      select: function( event, ui ) {
        let payload = {
          query: ui.item._query,
          latitude: latitude ? parseFloat(latitude) : null,
          longitude: longitude ? parseFloat(longitude) : null,
          rank: ui.item._rank,
          item: {
            type: ui.item.type,
            name: ui.item.name,
            context: ui.item.context,
            url: ui.item.url,
            latitude: ui.item.latitude,
            longitude: ui.item.longitude,
            uuid: ui.item.uuid,
          },
        };
        let blob = new Blob([JSON.stringify(payload)], {type: 'application/json'});
        navigator.sendBeacon(autocompleteHitsUrl, blob);

        $("#search-form").attr('action', ui.item.url).submit();
      }
    }).autocomplete( "instance" )._renderItem = function( ul, item ) {
      let badge =
          item.type === 'municipality' ? '<span class="badge badge-primary">Ville</span>' :
              (item.type === 'parish' ? '<span class="badge badge-success">Paroisse</span>' :
                  (item.type === 'church' ? '<span class="badge badge-light-blue">Église</span>' :
                      ''));
      return $( "<li>" )
        .append( "<div class='row'><div class='col-md autocomplete-name'>" + item.name + " " + badge + "</div>" +
            "<div class='col-md text-end' style='font-style: italic'>" + item.context + "</div></div>" )
        .appendTo( ul );
    };
});

/*
 * noUISlider for hour range.
 */
$(function () {
  let $hourSliderRange = document.getElementById('hour-slider-range');
  let startHourMin = $("#hour-min").val() || 0;
  let startHourMax = $("#hour-max").val() || 24 * 60 - 1;
  noUiSlider.create($hourSliderRange, {
    start: [startHourMin, startHourMax],
    connect: true,
    range: {
      'min': 0,
      'max': 24 * 60 - 1
    },
    step: 5,
  });
  $hourSliderRange.noUiSlider.on('update', function( event ) {
    formatHourRange(Math.round(event[ 0 ]), Math.round(event[ 1 ]));
  });
  $hourSliderRange.noUiSlider.on('change', function( event ) {
    $("#hour-min").val(Math.round(event[ 0 ]));
    $("#hour-max").val(Math.round(event[ 1 ]));
    $("#hour-filter-form").submit();
  });
});

function formatHourRange(hourMin, hourMax) {
    $("#hour-label").text("De " + displayHourFromMinutes(hourMin) + " à "
        + displayHourFromMinutes(hourMax));
}

function displayHourFromMinutes(minutes) {
    let hours = Math.floor(minutes / 60);
    let minutesLeft = minutes % 60;
    return hours + "h" + (minutesLeft > 0 ? (minutesLeft < 10 ? '0' + minutesLeft : minutesLeft) : '');
}

function toggleDisplayFilters(element) {
  $(element).toggleClass('active');
  let $filtersContainers = $('#filters-container');
  $filtersContainers.toggleClass('d-none');
}

/*
 * Watch map movement.
 *
 * Requires JQuery (to wait for the iframe to be loaded).
 */
$(document).ready(function () {
  let $mapIframe = $('#map-iframe');

  async function getMap() {
    let mapObjectName = $mapIframe.attr('data-map-name');
    let map;
    while (!map) {
      await new Promise(resolve => setTimeout(resolve, 200));
      map = document.getElementById("map-iframe").contentWindow[mapObjectName];
    }
    return map;
  }

  async function handleIframeLoaded() {
    const map = await getMap();

    map.on('moveend', function (evt) {
      let bounds = map.getBounds();
      $("#min-lat-input").val(bounds._southWest.lat);
      $("#min-lng-input").val(bounds._southWest.lng);
      $("#max-lat-input").val(bounds._northEast.lat);
      $("#max-lng-input").val(bounds._northEast.lng);
      $("#search-in-this-area-col").removeClass('d-none');
    });
  }

  // Check if the iframe is already loaded
  if ($mapIframe.get(0).contentWindow.document.readyState === 'complete') {
    console.log('iframe already loaded');
    handleIframeLoaded();
  } else {
    // Wait for the iframe to be loaded
    $mapIframe.load(function () {
      handleIframeLoaded();
    });
  }
});

/**
 * Handle search around me button.
 */
$(document).ready(function () {
  if (navigator.geolocation) {
    $('#search-around-me-col').removeClass('d-none');

    let $searchAroundMe = $('#search-around-me-btn');
    $searchAroundMe.click(function (e) {
      // disable button submit on click
      e.preventDefault();

      let originalText = $searchAroundMe.html();
      // Change the text of the button
      $searchAroundMe.html('<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Recherche ...');

      navigator.geolocation.getCurrentPosition(function (position) {
        $("#position-latitude-input").val(position.coords.latitude);
        $("#position-longitude-input").val(position.coords.longitude);
        $("#search-around-me-form").submit();
      }, function (error) {
        console.log('error getting position', error);
        alert('Erreur lors de la récupération de votre position');
        // Change the text of the button
        $searchAroundMe.html(originalText);
      });
    });
  }

});
