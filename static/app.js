$(document).ready(function () {
    if (!window.console) window.console = {};
    if (!window.console.log) window.console.log = function () {
    };
    console.log('Ready')

    updater.start();

    $("[id^=slid]").change(function () {
        var slider_value = $(this).val();
        var chan = $(this).attr('chan')
        //console.log("#pwm" + chan + " = " + slider_value);
        $("#pwm" + chan).val(slider_value)
        manualUpdate();
    });

    $("a[name^=button]").click(function () {
        console.log("Clicked " + $(this).text() + ", cmd=" + $(this).attr("cmd"))
        UI[$(this).attr("cmd")]();
    });

    $("[id^=pwm]").change(function () {
        console.log("Update position " + $(this).text())
        manualUpdate();
    })

});

var UI = {
    updatePosition: function (obj) {
        console.log("UI.updatePosition(): " + obj)
        for (let key in obj) {
            let pwm = obj[key];
            console.log(pwm)
            for (let i = 0; i < pwm.length; i++) {
                // console.log(key + i + "=" + pwm[i])
                $("#" + (key + i)).val(pwm[i])
                $("#" + ("slid" + i)).val(pwm[i])
            }
        }
    },

    getPosition: function () {
        console.log("UI.getPosition():")
        var target_pwm = [];

        $("[id^=pwm]").each(function () {
            // console.log($(this).val())
            target_pwm.push(Math.round(parseFloat($(this).val())))
        });
        return target_pwm;
    },

    Sequence: [],

    Add: function () {
        var data = {
            "target_pwm": UI["getPosition"]()
        };
        console.log("Appending: " + JSON.stringify(data))
        // var current_text = $("#sequencye").text() + JSON.stringify(data) + '\n';'
        var ix = UI.Sequence.length
        UI.Sequence[ix] = {
            'frame': UI.Sequence.length,
            'target_pwm': UI["getPosition"](),
            'speed': parseInt($("#speed").val()),
            'sleep': parseInt($("#sleep").val()),
            'sleep_before': parseInt($("#sleep_before").val()),
            'match_speed': $("#match_speed").is(":checked"),
        };
        console.log(UI.Sequence[ix]);
        var sequencye_text = $("#sequencye").val()
        $("#sequencye").val(sequencye_text + (JSON.stringify(UI.Sequence[ix]) + ',\n'));

    },

    Clear: function () {
        $("#sequencye").val("");
        UI.Sequence = [];
    },

    Load: function () {
        console.log("Loading Json")
        var text = $("#sequencye").val().trim()

        if(text[text.length-1]==',') {
            text = text.slice(0, text.length - 1);
        }
        try{
            UI.Sequence = JSON.parse("[" + text +"]")
        }
        catch (e) {
            console.log("ERROR in UI.Load function: ")
            console.log(e)
        }
    },

    SaveFile: function () {
        console.log("SaveFile")
        var data = {
            "id": "button",
            "body": UI.Sequence,
            "cmd": "SaveFile",
            "filename": $("#filename").val().trim()
        };
        updater.socket.send(JSON.stringify(data));
    },

    LoadFile: function () {
        console.log("LoadFile")
        var data = {
            "id": "button",
            "cmd": "Loadfile",
            "filename": $("#load_file").val().trim()
        };
        updater.socket.send(JSON.stringify(data));
    },

    Run: function () {
        console.log("Run :")
        var data = {
            "id": "button",
            "body": UI.Sequence,
            "cmd": "Run",
            "number_of_times": parseInt($("#run_times").val()),
        };
        updater.socket.send(JSON.stringify(data));
    },

    FromLoadedFile: function(obj){
        console.log("UI.FromLoadedFile(): " + obj);
        UI.Clear();
        for (let i = 0; i < obj.body.length; i++) {
            console.log(obj.body[i])
            var sequencye_text = $("#sequencye").val()
            $("#sequencye").val(sequencye_text + (JSON.stringify(obj.body[i]) + ',\n'));
        };
        UI.Load();

    }
};

var manualUpdate = function () {
    // console.log("Manual Update");

    var target_pwm = [];

    $("[id^=pwm]").each(function () {
        // console.log($(this).val())
        target_pwm.push(Math.round(parseFloat($(this).val())))
    });
    // console.log("target_pwm = " + target_pwm);

    var data = {
        "id": "button",
        "body": {"target_pwm": target_pwm},
        "cmd": "Update"
    };
    updater.socket.send(JSON.stringify(data));
};


var updater = {
    socket: null,

    start: function () {
        var url = "ws://" + location.host + "/ws";
        updater.socket = new WebSocket(url);
        updater.socket.onmessage = function (event) {
            updater.showMessage(event.data);
        }
    },

    showMessage: function (event_data) {
        console.log(event_data)

        try {
            let message = JSON.parse(event_data)
            let obj = message;
            let cmd = obj.cmd;
            let param = obj.param;
            console.log("showMessage: UI["+cmd+"]("+param+")")
            UI[cmd](param);
        } catch {
            console.log('could not process incomming message: ' + event_data)
        }
    }
};

