document.addEventListener("DOMContentLoaded", function () {
    var dataEl = document.getElementById("week-chart-data");
    var canvas = document.getElementById("weekReservationsChart");
    if (!dataEl || !canvas || typeof Chart === "undefined") {
        return;
    }

    var payload = JSON.parse(dataEl.textContent);
    var dayMap = {
        Mon: "Lun",
        Tue: "Mar",
        Wed: "Mer",
        Thu: "Jeu",
        Fri: "Ven",
        Sat: "Sam",
        Sun: "Dim"
    };
    var localizedLabels = (payload.labels || []).map(function (label) {
        return String(label).replace(/^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b/, function (m) {
            return dayMap[m] || m;
        });
    });

    new Chart(canvas, {
        type: "bar",
        data: {
            labels: localizedLabels,
            datasets: [
                {
                    label: "Réservations actives",
                    data: payload.values || [],
                    backgroundColor: "#1B6B9E",
                    hoverBackgroundColor: "#134668",
                    borderColor: "#87C1E9",
                    borderWidth: 1,
                    borderRadius: 8,
                    maxBarThickness: 44
                }
            ]
        },
        options: {
            responsive: true,
            plugins: {
                legend: { display: false }
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: {
                        color: "#4A5A68",
                        font: { family: "'Work Sans', sans-serif", weight: "600" }
                    }
                },
                y: {
                    beginAtZero: true,
                    grid: { color: "#DCECF8" },
                    ticks: {
                        precision: 0,
                        color: "#4A5A68",
                        font: { family: "'Work Sans', sans-serif" }
                    }
                }
            }
        }
    });
});
