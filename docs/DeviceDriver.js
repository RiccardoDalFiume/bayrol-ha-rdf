// Forward declaration of application object.
var EmWiApp;

// Ensure that the application file is loaded before ...
if ( !EmWiApp )
  throw new Error( "The application file '_project.js' isn't yet loaded!" );

/*******************************************************************************
*                        MQTT CLIENT + JSON PROTOCOL DEFINES                   * 
*******************************************************************************/
// Mqtt client
var client;

// register API server and server API
const registerApi = "https://www.bayrol-poolaccess.de/api/";
const server = "wss://www.bayrol-poolaccess.de:8083/";
//App-link: https://www.ielportal.de/app/A-xxxxxx

// Device Code / Token / Serial / Type
var device_token_cookie = "device_token";
var device_serial = "";
var device_serial_cookie = "device_serial";
const device_code_length = 8;
const device_code_prefix = "A-"
var device_type_cookie = "device_type";

// Topic data
const topicStart = "d02";
const topic_separator = "/";
const KIND = {
  subscribe: 'v',
  publish: 's',
  request: 'g',
  values: 'v'
};
Object.freeze(KIND);

// Topic items count
const topicItemsCount = 4;

// Function getTopic
// returns the topic string for an object
function getTopic( aType, aId, aKind ) {
  /*
  1.1  = e_phSetpoint (1 = Typ „Num-Parameter“, 1 = Item (Topic) „pH Sollwert“)
  2.1 = e_ph (2 = Typ „Num-Variable“, 1 =Item (Topic) „pH Messwert“)
  3.101 = e_emailActive1 (3 = Typ „Enum-Parameter“, 101 = Item (Topic) „E-Mail Empfänger 1 aktiv“)
  */
  var sep = topic_separator;
  var topic = topicStart + sep + device_serial + sep + aKind + sep + aType;
  if ( aId !== null )
    topic += "." + aId;

  return topic;
}

/*******************************************************************************
* APP STATE 
*******************************************************************************/
const AppState = {
  Active  : 0,
  Passive : 1,
  Hidden :  2
}

/*******************************************************************************
*                   REGISTERED EMWI OBJECTS                                    * 
*******************************************************************************/
// Object status flags
const ObjectStatus = {
  Unregistered      : 0x0000,  
  UnregisterPending : 0x0001,
  Registered        : 0x0002,
  RegisterPending   : 0x0004,
  SetValuePending   : 0x0008
}
Object.freeze(ObjectStatus)

// Auto Object class
function AutoObject() {
  this.Id = 0;
  this.Handle = null; 
  this.Value = null; 
  this.Status = ObjectStatus.Unregistered;
}

// Num Object class
function NumObject() {
  this.Id = 0;
  this.Handle = null; 
  this.Value = null; 
  this.Min = null; 
  this.Max = null; 
  this.Status = ObjectStatus.Unregistered;
}

// MessageItem class
function MessageItem() {
  this.Id = 0;
}

// EventLogItem class
function EventLogItem() {
  this.Timestamp = 0;
  this.Class = 0;
  this.Type = 0;
  this.ObjectType = 0;
  this.ObjectId = 0;
  this.OldValue = 0;
  this.NewValue = 0;
}


// Max number of items in one array(containing items received form the server)
const MAX_ARRAY_ITEMS_COUNT = 250;

// Arrays storing the registered objects
var Nums   = new Array( EmWiApp.Nums.Id.LAST_ID );
var Enums  = new Array( EmWiApp.Enums.Id.LAST_ID );
var Events = new Array( EmWiApp.Menus.EventId.LAST_ID );
var Conditions = new Array( EmWiApp.Conditions.Id.LAST_ID );
var Codes = new Array( EmWiApp.Codes.Id.LAST_ID );
var Strings = new Array( EmWiApp.Strings.Id.LAST_ID );
// Array storing the Messages
var Messages = new Array( MAX_ARRAY_ITEMS_COUNT );
// Array storing the Ack Pending Messages
var MessagesAckPending = new Array( EmWiApp.Messages.Id.LAST_ID );
// Array storing the EventLogs
var EventLog = new Array( MAX_ARRAY_ITEMS_COUNT );

// Function createObject
function createObject( aType ) {
  switch( aType ) {
    case EmWiApp.Device.TopicIDs.e_topic_num            : return new NumObject();  
    case EmWiApp.Device.TopicIDs.e_topic_msg_list       : return new MessageItem();
    case EmWiApp.Device.TopicIDs.e_topic_eventlog_event : return new EventLogItem();
    default                                             : return new AutoObject();
  }
}

// Function getArrayforType
// returns the Array storing the objects of type aType
function getArrayforType( aType ) {
  switch( aType ) {
    case EmWiApp.Device.TopicIDs.e_topic_num            : return Nums;  
    case EmWiApp.Device.TopicIDs.e_topic_enum           : return Enums;
    case EmWiApp.Device.TopicIDs.e_topic_gui_event      : return Events;
    case EmWiApp.Device.TopicIDs.e_topic_cond           : return Conditions;
    case EmWiApp.Device.TopicIDs.e_topic_code           : return Codes;
    case EmWiApp.Device.TopicIDs.e_topic_string         : return Strings;
    case EmWiApp.Device.TopicIDs.e_topic_string         : return Strings;
    case EmWiApp.Device.TopicIDs.e_topic_msg_list       : return Messages;
    case EmWiApp.Device.TopicIDs.e_topic_msg_shown      : return MessagesAckPending;
    case EmWiApp.Device.TopicIDs.e_topic_eventlog_event : return EventLog;
    default:
      console.warn('GUI: Unhandled object type ', aType );
      return null;
  }
}

// Function getObjectsArrayLength
function getObjectsArrayLength( aType ) {
  var arr = getArrayforType( aType );
  if ( !arr )
    return 0;

  return arr.length;
}

// Function cleanupArray
function cleanupArray( aArray ) {
  let i = 0;
  let len = aArray.length;
  for( ; i < len; i++ ) {
    aArray[i] = null;
  }
}

// Function getArrayItemsCount
function getArrayItemsCount( aArray ) {
  let i = 0;
  let len = aArray.length;
  let count = 0;
  for( ; i < len; i++ ) {
    if ( aArray[i] ) {
      count++;
    }
    else {
      // exit for
      i = len;
    }

  }
  return count;
}

// Function isArrayIndexValid
// returns true if index is valid, otherwise false
function isArrayIndexValid( aType, aIndex ) {
  var isValid = ( aIndex >= 0 ) && ( aIndex < getObjectsArrayLength( aType ) );
  
  if ( !isValid )
    console.error( 'GUI_ERROR: Invalid ' + getObjectTypeString( aType ) + ' array index ' + aIndex );

  return isValid;
}

// Function getObjectByTypeAndId
// returns the object stored in the array
function getObjectByTypeAndId(aType, aId) {
  // check aId validity
  if ( aId < 0 || aId >= getObjectsArrayLength( aType ) ) {
    return null;
  }

  var array = getArrayforType( aType );
  if ( !array )
    return null;

  return array[aId];
}

// Function storeObject
// stores the object in the corresponding array
function storeObject(aType, aId, aObj) {
  // check aId validity
  if ( ! isArrayIndexValid( aType, aId ) )
    return;

  var array = getArrayforType( aType );
  if ( !array )
    return;

  array[aId] = aObj;
}

// Function getObjectTypeString
// return object type as string
function getObjectTypeString( aType ) {
  switch( aType ) {
    case EmWiApp.Device.TopicIDs.e_topic_num            : return "Num";
    case EmWiApp.Device.TopicIDs.e_topic_enum           : return "Enum";
    case EmWiApp.Device.TopicIDs.e_topic_gui_event      : return "Event";
    case EmWiApp.Device.TopicIDs.e_topic_cond           : return "Condition";
    case EmWiApp.Device.TopicIDs.e_topic_code           : return "Code";
    case EmWiApp.Device.TopicIDs.e_topic_string         : return "String";
    case EmWiApp.Device.TopicIDs.e_topic_msg_list       : return "MessageList";
    case EmWiApp.Device.TopicIDs.e_topic_eventlog_event : return "EventLog";
    case EmWiApp.Device.TopicIDs.e_topic_top_msg        : return "TopMessage";
    case EmWiApp.Device.TopicIDs.e_topic_device_status  : return "DeviceStatus";
    default:
      console.warn('GUI: Unhandled object type ', aType );
      return "";
  }
}

// Function isStringValueObject
// returns true if the object of the specified type has a string value
function isStringValueObject( aType ) {
  switch( aType ) {
    case EmWiApp.Device.TopicIDs.e_topic_code   : 
      return true;
    case EmWiApp.Device.TopicIDs.e_topic_string : 
      return true;
    default                                     : 
      return false;
  }
}

// Function isSingleObject
// returns true if the type is for a single object not a list
function isSingleObject( aType ) {
  switch( aType ) {
    case EmWiApp.Device.TopicIDs.e_topic_msg_list  : 
      return false;
    case EmWiApp.Device.TopicIDs.e_topic_eventlog_event  : 
      return false;
    default                                        :
      return true;
  }
}

// Function isAutoObject
// returns true if the type is for an autoobject
function isAutoObject( aType ) {
  switch( aType ) {
    case EmWiApp.Device.TopicIDs.e_topic_num       : return true;
    case EmWiApp.Device.TopicIDs.e_topic_enum      : return true;
    case EmWiApp.Device.TopicIDs.e_topic_gui_event : return true;
    case EmWiApp.Device.TopicIDs.e_topic_cond      : return true;
    case EmWiApp.Device.TopicIDs.e_topic_code      : return true;
    case EmWiApp.Device.TopicIDs.e_topic_string    : return true;
    default                                        : return false;
  }
}

// Function getTopicId
function getTopicId( aId ) {
  return parseInt( String(aId).split( "." )[0] );
}

// Function getId
function getObjectId( aId ) {
  var ids = String(aId).split( "." );
  if ( ids.length != 2 )
    return parseInt( aId );
  return parseInt( ids[1] );
}

/*******************************************************************************
*                        JSON DATA                                             * 
*******************************************************************************/
// JSON data properties
const JSONProp = {
  topic : 't',
  value : 'v',
  dec   : 'dec',
  min   : 'min',
  max   : 'max',
  limit : 'limit'
}

// Function getPublishJson
// returns value json for publishing to websocket
function getPublishJson( aType, aObject ) {
  if ( !aObject  ) {
    console.error( 'GUI: Invalid object provided!' );
    return '';
  }

  // json object begin
  var data = '{'; 
  var val = "";
  var id = 0;
  var addIdToTopic = true;
  var result = true;
  
  if ( isAutoObject( aType ) ) {
    id = aObject.Id;
    // value
    val = "" + aObject.Value;
    if ( aType == EmWiApp.Device.TopicIDs.e_topic_enum ) {
      // for enum, add data type e_data_type_enum_value to the value   
      val = '"' + EmWiApp.Device.TopicIDs.e_data_type_enum_value + '.' + val + '"';
    } else if ( isStringValueObject( aType ) ) {
      val = '"' + val + '"';
    }
  } else {
    // handle other objects / topics
    switch( aType ) {
      // Message shown
      case EmWiApp.Device.TopicIDs.e_topic_msg_shown :
        addIdToTopic = false;
        // value is e_topic_msg.<message id>
        val = '"' + EmWiApp.Device.TopicIDs.e_topic_msg + "." + aObject.Id  + '"';
        break;
      // Call device function
      case EmWiApp.Device.TopicIDs.e_topic_function :
        id = aObject;
        // value is 1
        val = '1';
        break;
      default : 
        console.warn( "GUI: Unhandled topic ", aType );
        result = false;
        break;
    }
  }

  if ( !result )
    return "";

  // add topic
  data += '"' + JSONProp.topic + '":"' + aType 
  if ( addIdToTopic )
    data +=  '.' + id + '"';
  else
    data +=  '"';

  // add value
  data += ',"' + JSONProp.value + '":' + val;

  // for num objects add min and max
  if ( aType == EmWiApp.Device.TopicIDs.e_topic_num ) {
    data += ',"' + JSONProp.min + '":' + aObject.Min;
    data += ',"' + JSONProp.max + '":' + aObject.Max;
  }

  // add json object end
  data = data + '}';

  return data;
}

// Function getRequestJson
// returns json string needed for requesting data form teh websocket
function getRequestJson( aType ) {
  var data = '';
  switch( aType )
  {
    case EmWiApp.Device.TopicIDs.e_topic_eventlog_event : 
      var data = '{"' + JSONProp.limit + '":' + MAX_ARRAY_ITEMS_COUNT + '}'; 
      break;

    default : 
      break;
  }

  return data;
}


/*******************************************************************************
*                        COOKIES HANDLING FUNCTIONS                            * 
*******************************************************************************/
// Cookie expiration in minutes ( 1000 years )
const COOKIE_EXPIRE = 1000 * 365 * 24 * 60;

// Function to store a cookie
function setCookie( name, value, mins ) {
    var expires = "";
    if ( mins ) {
        var date = new Date();
        date.setTime( date.getTime() + ( mins * 60 * 1000 ) );
        expires = "; expires=" + date.toUTCString();
    }
    document.cookie = name + "=" + value + expires + "; path=/";
}

// Function to get a cookie value
function getCookie(name) {
    var nameEQ = name + "=";
    var ca = document.cookie.split(';');
    for( var i=0; i < ca.length; i++) {
        var c = ca[i];
        while ( c.charAt(0) ==' ' ) c = c.substring( 1, c.length );
        if ( c.indexOf( nameEQ ) == 0) return c.substring( nameEQ.length, c.length );
    }
    return null;
}

// Function to delete a cookie
function deleteCookie( name ) {
  var date = new Date();
  console.log( "GUI: Delete cookie", name, "expires=", date.toUTCString() )
  document.cookie = name + "=;expires=" + date.toUTCString() + "; path=/";
}

/*******************************************************************************
*                        LOCALSTORAGE HANDLING FUNCTIONS                            * 
*******************************************************************************/
// Function to store an item in LocalStorage if available, otherwise as cookie
function storeItem( name, value, mins ) {
  if ( localStorage ) {
    console.log( "GUI: Store item to LocalStorage:", name, value );
    localStorage.setItem( name, value );
  } else {
    console.error( "GUI: No LocalStorage support !" );
    setCookie( name, value, mins );
  }
}

// Function to get a local storage item
function getStoredItem( name ) {
  if ( localStorage ) {
    var item = localStorage.getItem( name );
    console.log( "GUI: Get item from LocalStorage:", name, item );
    return item;
  } else {
    console.error( "GUI: No LocalStorage support !" );
    return getCookie( name );
  }
}

// Function to delete a local storage item
function deleteStoredItem( name ) {
  if ( localStorage ) {
    console.log( "GUI: Delete LocalStorage item", name )
    return localStorage.removeItem( name );
  } else {
    console.error( "GUI: No LocalStorage support !" );
    deleteCookie( name );
  }
}

// Function to transfer all the cookies to LocalStorage if LocalStorage is available
function transferCookiesToLS() {
  if ( localStorage ) {
    transferCookieToLS( device_token_cookie );
    transferCookieToLS( device_serial_cookie );
    transferCookieToLS( device_type_cookie );
  } else {
    console.error( "GUI: No LocalStorage support !" );    
  }
}

// Function to transfer the cookie specified by name to LocalStorage
function transferCookieToLS( name ) {
  var cookieValue = getCookie( name );
  if ( cookieValue ) {
    storeItem( name, cookieValue, COOKIE_EXPIRE );
    deleteCookie( name );
  }
}


/*******************************************************************************
*                        STRING HANDLING FUNCTIONS                            * 
*******************************************************************************/
if ( !String.prototype.format ) {
String.prototype.format = function() {
    var formatted = this;
    for (var i = 0; i < arguments.length; i++) {
        var regexp = new RegExp('\\{'+i+'\\}', 'gi');
        formatted = formatted.replace(regexp, arguments[i]);
    }
    return formatted;
};
}


/*******************************************************************************
*                        DEVICE DRIVER OBJECT                                  * 
*******************************************************************************/
DeviceDriver = (function()
{
  var _dd = {  };
  // internet status
  var internet;
  // EmWi Device obejct
  var _device  = null;

  
  /*******************************************************************************
  * FUNCTION:
  *   Initialize
  *
  * DESCRIPTION:
  *   The function Initialize() initializes the module and prepares all
  *   necessary things to access or communicate with the real device.
  *   The function has to be called from your main module, after the initialization
  *   of your GUI application.
  *
  * ARGUMENTS:
  *   None
  *
  * RETURN VALUE:
  *   None
  *
  *******************************************************************************/
  _dd.Initialize = function() {
    _device = EmWiApp._GetAutoObject( EmWiApp.Device.Device );
    if ( !_device ) 
      throw new Error( "Failed to obtain Device object!" );

    // TODO: Delete this later on again. This is only a Patch to use LocalStorage over Cookies.
    // Because of the "lifetime of cookies set by JavaScript is limited to 7 days for "
    transferCookiesToLS();

    // Add Event listeners for the internet connection status
    window.addEventListener("offline", (event) => {
      _dd.setInternetStatus( false );
    });

    window.addEventListener("online", (event) => {
      _dd.setInternetStatus( true );
    });

    // Set initial internet connection status
    _dd.setInternetStatus( navigator.onLine );

    _dd.checkAppStateStart();

  };

  _dd.setInternetStatus = function( aStatus )  {
    if ( internet === aStatus )
      return;

    internet = aStatus;
    if ( aStatus )
      _dd.I_AppConnect();
    else
      _device.OnSetErrorCode( EmWiApp.Device.ErrorCode.NoInternetConnection );
  }


  /*******************************************************************************
  * FUNCTION:
  *   DeviceDriver_Deinitialize
  *
  * DESCRIPTION:
  *   The function DeviceDriver_Deinitialize() deinitializes the module and
  *   finalizes the access or communication with the real device.
  *   The function has to be called from your main module, before the GUI
  *   application will be deinitialized.
  *
  * ARGUMENTS:
  *   None
  *
  * RETURN VALUE:
  *   None
  *
  *******************************************************************************/
  _dd.Deinitialize = function()
  {
    _device = null;
    _dd.checkAppStateStop();
  };


  /*******************************************************************************
  * FUNCTION:
  *   I_AppConnect
  *
  * DESCRIPTION:
  *   For mobiles if the application is not installed opens AppInstall popup.
  *   Checks if the registration was already done - cookies with device token
  *   and serial exists. If device token found, connects to the server, 
  *   otherwise opens the AppConnect popup.
  * 
  * ARGUMENTS: NONE
  *
  * RETURN VALUE:
  *   1 for success, 0 in case of error
  *
  *******************************************************************************/
  _dd.I_AppConnect = function( ) {   
    // for mobiles if the application is not installed or if it is not direct access opens AppInstall popup
    if ( MobileApp.IsMobileOrTablet() && !MobileApp.IsStandalone() && !isDirectConnection() ) {
      _device.OnSetErrorCode( EmWiApp.Device.ErrorCode.AppInstallRequired );      
      return 1;
    }

    // get device token and serial from LocalStorage/cookies
    device_token = getStoredItem( device_token_cookie );
    device_serial = getStoredItem( device_serial_cookie );

    // if in browser, check if the app link code is provided
    if ( ! MobileApp.IsStandalone() ) {
      // get code parameter from the URL
      var code = getDeviceCode();
      if ( code ) {
        // if code provided, do the connection with the device using this code
        _dd.I_AppConnectDevice( code );
        return 1;
      } 
    }

    // check if the connection was already done( token cookie exists )
    if ( ! device_token || ! device_serial ) {
      // no cookies -> set ErrorCode to AppCodeNeeded, the AppConnect popup will be displayed after splash screen
      _device.OnSetErrorCode( EmWiApp.Device.ErrorCode.AppCodeNeeded );
      return 1;
    }

    // if token found, trigger OnRegistrationDone
    _dd.onAppConnectDone();
    
    return 1;
  };

/*******************************************************************************
  * FUNCTION:
  *   I_AppDisconnect
  *
  * DESCRIPTION:
  *   The function I_AppDisconnect removes the stored cookies for device token
  *   and serial and opens the AppConnect popup.
  * 
  * ARGUMENTS: NONE
  *
  * RETURN VALUE:
  *   1 for success, 0 in case of error
  *
  *******************************************************************************/
  _dd.I_AppDisconnect = function( ) {
    // delete cookies
    deleteStoredItem( device_token_cookie );
    deleteStoredItem( device_serial_cookie );
    deleteStoredItem( device_type_cookie );

    // close websocket
    _dd.I_Disconnect();

    // open AppConnect
    _device.TriggerModalPopup( EmWiApp.Device.ModalPopupId.AppConnect );
  }
  
  /*******************************************************************************
  * FUNCTION:
  *   I_PasteAppLinkCode
  *
  * DESCRIPTION:
  *   The function pastes the App link code from the clipboard.
  *
  * ARGUMENTS: NONE
  *
  * RETURN VALUE:
  *   1 for success, 0 in case of error
  *
  *******************************************************************************/
  _dd.I_PasteAppLinkCode = function() {
  
    // paste code from clipboard
    MobileApp.ClipboardPaste( _dd.onClipboardPasteSuccess, _dd.onClipboardPasteError );

    return 1;
  }

  /*******************************************************************************
  * FUNCTION:
  *   I_AppConnectDevice
  *
  * DESCRIPTION:
  *   The function connects the app with the device using the applink code provided
  *   as parameter.
  *
  * ARGUMENTS: NONE
  *
  * RETURN VALUE:
  *   1 if code was found, 0 in case of error
  *
  *******************************************************************************/
  _dd.I_AppConnectDevice = function( aCode ) {   
    // check code 
    if ( !aCode ) {
      console.error('GUI: Empty app link code!');
      _dd.onAppConnectError();
      return 0;
    }

    console.log('GUI: Try connecting app to the device.');
    // send AJAX Request to the device api server to register the device
    var xhttp = new XMLHttpRequest();
    xhttp.onreadystatechange = function() {
      if (this.readyState == 4) {
        try {
          var ret = JSON.parse(this.responseText);
          if (this.status == 200) {
            if ( ret.accessToken && ret.deviceSerial ) {
              console.log('MQTT: Connection Token ', device_token);
              if ( ( device_token  !== ret.accessToken ) || 
                   ( device_serial !== ret.deviceSerial ) ) {  
                device_token = ret.accessToken;
                device_serial = ret.deviceSerial;

                // delete device type cookie
                deleteStoredItem( device_type_cookie );
                // store device token and serial into cookies if no direct connection
                if ( !isDirectConnection()  ) {
                  console.log('GUI: Device changed, store the device token and serial in cookies.');
                  // store device token into LocalStorage or cookie if LocalStorage is not available
                  storeItem( device_token_cookie, device_token, COOKIE_EXPIRE );
                  // store device serial into LocalStorage
                  storeItem( device_serial_cookie, device_serial, COOKIE_EXPIRE );
                }
              }

              _dd.onAppConnectDone();
            }
            else {
              console.error('MQTT: No token returned!');                
              _dd.onAppConnectError();
            }
          } else {
            console.error('MQTT: ' + this.responseText);
            _dd.onAppConnectError();
          }
        } catch (e) {
          console.error('MQTT: ', e);
          _dd.onAppConnectError();
        }
      }
    };
    xhttp.open("GET", registerApi + "?code=" + aCode, true);
    xhttp.send();  

    return 1;
  };

  _dd.onAppConnectError = function() {
    // open AppConnect Error popup
    _device.OnSetErrorCode( EmWiApp.Device.ErrorCode.AppConnectError );
  };

  _dd.onAppConnectDone = function() {    
    // trigger Device object OnAppConnectDone slot
    _device.OnAppConnectDone( this );
  };

  _dd.onConnectionError = function( errorCode ) {
    if ( navigator.onLine )
      _device.OnSetErrorCode( errorCode );
    else
      _device.OnSetErrorCode( EmWiApp.Device.ErrorCode.NoInternetConnection );
  };
  
  /*******************************************************************************
  * FUNCTION:
  *   I_GetDeviceType
  *
  * DESCRIPTION:
  *   Returns the device type from the cookie.
  *
  * ARGUMENTS: NONE
  *
  * RETURN VALUE:
  *   Device type enum item (see enum Device::DeviceType)
  *
  *******************************************************************************/
  _dd.I_GetDeviceType = function() {   
    // for direct connection don't use cookie
    if ( isDirectConnection() )  
      return EmWiApp.Device.DeviceType.neutral;

    var typeStr = getStoredItem( device_type_cookie );
    if ( !typeStr || isNaN( typeStr ) )
      return EmWiApp.Device.DeviceType.neutral;
    
    return parseInt( typeStr );
  }

  /*******************************************************************************
  * FUNCTION:
  *   I_SaveDeviceType
  *
  * DESCRIPTION:
  *   Stores the device type into a cookie.
  *
  * ARGUMENTS: 
  *   aDeviceType - device type enum item (see enum Device::DeviceType)
  *
  * RETURN VALUE:
  *   NONE
  *
  *******************************************************************************/
  _dd.I_SaveDeviceType = function( aDeviceType ) { 
    // for direct connection don't save cookie
    if ( !isDirectConnection() )  
      storeItem( device_type_cookie, aDeviceType, COOKIE_EXPIRE );
  }

  /*******************************************************************************
  * FUNCTION:
  *   I_RegisterObject
  *
  * DESCRIPTION:
  *   The function registers an object of type aType on the device.
  *
  * ARGUMENTS:
  *   aType   - The object type, see enum Device::TopicIDs
  *   aId     - The object id
  *   aObject - The object
  *
  * RETURN VALUE:
  *   Acknowledge 1 (true) or 0 (false)
  *
  *******************************************************************************/
  _dd.I_RegisterObject = function( aType, aId, aObject ) {   
    if ( !aObject ) {
      console.error( 'GUI: Invalid object ', aObject );      
    }

    // check aId validity
    if ( ! isArrayIndexValid( aType, aId ) )
      return 0;

    var obj = getObjectByTypeAndId( aType, aId );
    var typeStr = getObjectTypeString(aType);
    if( obj && obj.Handle )
    {
      console.warn( 'GUI: ' + typeStr + " " + aId + " already registered!" );
      return 0;
    }

    console.log("GUI: Register " + typeStr + " " + aId );
    
    // create autoobject if not already created
    if ( !obj ) {
      obj = createObject( aType );
      if ( !obj ) {
        console.error( 'GUI: Failed to create object of type ', aType );
        return 0;
      }
    }
    // set Id, Chora object
    obj.Id = aId;
    obj.Handle = aObject;
    // if object is in UnregisterPending remove the flag
    if ( ( obj.Status & ObjectStatus.UnregisterPending ) > 0 )
    {
      obj.Status &= ~ObjectStatus.UnregisterPending;
    }

    obj.Status |= ObjectStatus.RegisterPending;
    // update with the last stored value    
    // TODO: Comment if value caching is not needed
    if ( obj.Value !== null ) {
      aObject.UpdateValue( obj.Value );
      console.log( "GUI: " + typeStr + " object " + aId + " value updated to " + obj.Value + " (via cache!)" );
    }

    storeObject( aType, aId, obj );

    if ( !client || !client.connected ) {
      console.warn('MQTT: Client not yet connected!');
    }

    _dd.registerObject( aType, obj );

    return 1;
  };

  // subscribe and request data from server
  _dd.registerObject = function( aType, aObj ) {
    if ( !aObj  ) {
      console.error("GUI: Invalid object provided!");
      return;
    }

    var typeStr = getObjectTypeString(aType);

    if ( !client || !client.connected ) {
      console.warn('MQTT: Subscription skipped for ' + typeStr + ' ' + aObj.Id );
      return;
    }

    // subscribe
    const topicS = getTopic( aType, aObj.Id, KIND.subscribe );
    client.subscribe(topicS, (err) => {
      if ( !err ) {
        console.log('MQTT: Subscribed to ', topicS)
        // request data
        const topicR = getTopic( aType, aObj.Id, KIND.request );
        client.publish(topicR, '', (err) => {
          if ( !err ) {
            console.log('MQTT: Published (Request) ', topicR )
            // clear UnregisterPending flag
            aObj.Status &= ~ObjectStatus.UnregisterPending;
            // clear Unregister flag
            aObj.Status &= ~ObjectStatus.Unregister;
            // clear RegisterPending flag
            aObj.Status &= ~ObjectStatus.RegisterPending;
            // set Registered flag
            aObj.Status |= ObjectStatus.Registered;

          } else {
            console.error('MQTT: Publish (Request) error for topic ', topicR, err );
          }
        });
      } else {
        console.error('MQTT: Subscribe error for topic ', topicS, err );
      }      
    });
  };

  /*******************************************************************************
  * FUNCTION:
  *   I_UnregisterObject
  *
  * DESCRIPTION:
  *   The function un-registers an object on the device.
  *
  * ARGUMENTS:
  *   aType      - The object type
  *   aid        - The object id
  *
  * RETURN VALUE:
  *   XInt32     - Acknowledge 1 (true) or 0 (false)
  *
  *******************************************************************************/
  _dd.I_UnregisterObject = function( aType, aId )
  {   
    // check aId validity
    if ( ! isArrayIndexValid( aType, aId ) )
      return 0;

    var obj = getObjectByTypeAndId( aType, aId );
    var typeStr = getObjectTypeString(aType);
    if( obj === 'undefined' || !obj ) {
      console.warn( "GUI: " + typeStr + " " + aId + " was already unregistered!" );
      return 0;      
    }

    console.log("GUI: Unregister " + typeStr + " " + aId);
    
    // clear object reference
    obj.Handle = null;

    // if object is in RegisterPending remove the flag
    if ( ( obj.Status & ObjectStatus.RegisterPending ) > 0 )
    {
      obj.Status &= ~ObjectStatus.RegisterPending;
    }

    // set flag UnregisterPending
    obj.Status |= ObjectStatus.UnregisterPending;

    if ( !client || !client.connected ) {
      console.warn('MQTT: Client not yet connected!');
      return 0;
    }

    // send unregister request to the server
    _dd.unregisterObject( aType, obj );
    
    return 1;
  }

  // send unsubscribe for aObj object to the server
  _dd.unregisterObject = function( aType, aObj ) {
    if ( !aObj  ) {
      console.error("GUI: Invalid object provided!");
      return;
    }

    const topic = getTopic( aType, aObj.Id, KIND.subscribe );
    client.unsubscribe(topic, (err) => {
      console.log('MQTT: Unsubscribe from ', topic)
      // clear RegisterPending flag
      aObj.Status &= ~ObjectStatus.RegisterPending;
      // clear Registered flag
      aObj.Status &= ~ObjectStatus.Registered;
      // clear UnregisterPending flag
      aObj.Status &= ~ObjectStatus.UnregisterPending;
      // set Unregistered flag
      aObj.Status |= ObjectStatus.Unregistered;

      // remove cached object
      // TODO: Uncomment next line if value caching is not needed
      //storeObject( aType, aObj.Id, null ) ;
    })
  }

  /*******************************************************************************
  * FUNCTION:
  *   I_SetValue
  *
  * DESCRIPTION:
  *   The function sets tha value into the stored object and publish it
  *   to the server.
  *
  * ARGUMENTS:
  *   aType  - The object type
  *   aId    - The object id
  *   aValue - The object new value
  *   aMin   - The object minim value(only for num objects)
  *   aMax   - The object max value(only for num objects)
  *
  * RETURN VALUE:
  *   Acknowledge 1 (true) or 0 (false)
  *
  *******************************************************************************/
  _dd.I_SetValue = function( aType, aId, aValue, aMin, aMax ) {
    // check aId validity
    if ( ! isArrayIndexValid( aType, aId ) )
      return 0;

    var obj = getObjectByTypeAndId( aType, aId );
    var typeStr = getObjectTypeString(aType);
    if( obj === 'undefined' || !obj )
    {
      console.warn( "GUI: " + typeStr + " " + aId + " not registered!" );
      return 0;
    }

    console.log("GUI: SetValue for " + typeStr + " " + aId + " to " + aValue );
    obj.Value = aValue;
    // Set Min and Max for Num objects
    if ( aType == EmWiApp.Device.TopicIDs.e_topic_num ) {
      obj.Min = aMin;
      obj.Max = aMax;
    }
    // set flag SetValuePending
    obj.Status |= ObjectStatus.SetValuePending;

    if ( !client || !client.connected ) {
      console.warn('MQTT: Client not yet connected!');
      return 0;
    }

    _dd.setValue( aType, obj );

  }

  // send new value for aObj object to the server
  _dd.setValue = function( aType, aObj ) {
    if ( !aObj  ) {
      console.error("GUI_WARNING: Invalid object provided!");
      return;
    }

    var topic = getTopic( aType, aObj.Id, KIND.publish );
    data = getPublishJson( aType, aObj );
    client.publish(topic, data, (err) => {
      console.log('MQTT: Publish (Set) to ', topic, " data ", data)
      // clear SetValuePending flag
      aObj.Status &= ~ObjectStatus.SetValuePending;
    });
  }

  /*******************************************************************************
  * FUNCTION:
  *   I_CallFunction
  *
  * DESCRIPTION:
  *   The function I_CallFunction is used to call a device function. 
  *
  * ARGUMENTS:
  *   aId    - The function id
  *
  * RETURN VALUE:
  *   Acknowledge 1 (true) or 0 (false)
  *
  *******************************************************************************/
  _dd.I_CallFunction = function( aId ) {
    if ( !client || !client.connected ) {
      console.warn('MQTT: Client not connected!');
      return 0;
    }

    if ( aId == EmWiApp.Menus.FunctionId.e_func_app_change_device ){
      _dd.I_AppDisconnect();
      return 1;
    }

    var type = EmWiApp.Device.TopicIDs.e_topic_function;
    console.log( 'GUI: Call function:', aId );
    var topic = getTopic( type, aId, KIND.publish );
    data = getPublishJson( type, aId );
    client.publish(topic, data, (err) => {
      console.log('MQTT: Publish (Set) to ', topic, " data ", data)
    });

    return 1;
  }

  /*******************************************************************************
  * FUNCTION:
  *   I_Connect
  *
  * DESCRIPTION:
  *   The function connects to socket.
  *
  * ARGUMENTS:
  *   aSock - Socket address
  *
  *******************************************************************************/
  _dd.I_Connect = function( aSock )
  {   
    const clientId = 'user_' + Math.random().toString(16).substr(2, 8)

    const options = {
      reconnectPeriod: 5000,
      rejectUnauthorized: false,  //self signed cert
      clientId: clientId,
      username: device_token,
      password: '*'
    };
    
    console.log('MQTT: Connecting ', clientId + ' to the server');
    client = mqtt.connect(server, options);

    client.on('error', (err) => {
      console.error('MQTT: ', 'Connection error ' + err.toString());
      client.end()
      _dd.onServerConnectionError();
    })

    client.on('reconnect', () => {
      console.log('MQTT: ', 'Client ' + clientId + ' REconnected.');
    })

    client.on('connect', () => {
      console.log('MQTT: ', 'Client ' + clientId + ' connected.');
      _dd.onConnectionDone();

      // subscribe to device status topic
      const topicS = getTopic( EmWiApp.Device.TopicIDs.e_topic_device_status, null, KIND.subscribe );
      client.subscribe(topicS, (err) => {
        if ( !err ) {
          console.log('MQTT: Subscribed to ', topicS)
        } else {
          console.error('MQTT: Subscribe error for topic ', topicS, err );
        }      
      });

      // process all pending requests
      _dd.processPendingRequests(); 

      // request data if app state was changed
      if ( requestDataFlag ) {
        _dd.requestData();
        requestDataFlag = false
      }

    })

    // Handle receives messages. First will get device list, later data values
    client.on('message', (topicU, message, packet) => {
      console.log('MQTT: Received Message ', topicU, message.toString());
      _dd.I_Receive( topicU, message );
    })

    client.on('close', () => {
      console.log('MQTT: ', 'Client ' + clientId + ' DISconnected.');
    })
  }

  _dd.onServerConnectionError = function() {
    _dd.onConnectionError( EmWiApp.Device.ErrorCode.NoServerConnection );
  }

  _dd.onConnectionDone = function() {
    _device.OnSetErrorCode( EmWiApp.Device.ErrorCode.Success );
  }
   
  /*******************************************************************************
  * FUNCTION:
  *   I_Disconnect
  *
  * DESCRIPTION:
  *   The function disconnects socket.
  *
  * ARGUMENTS:
  *   aSock - Socket address
  *
  *******************************************************************************/
  _dd.I_Disconnect = function()
  {   
    if ( client )
      client.end();
  }


  /*******************************************************************************
  * FUNCTION:
  *   I_Receive
  *
  * DESCRIPTION:
  *   The function receives data from socket.
  *
  * ARGUMENTS:
  *   aTopic - 
  *   aData - Data as handle
  *
  * RETURN VALUE:
  *   Acknowledge 1 (true) or 0 (false)
  *
  *******************************************************************************/
  _dd.I_Receive = function( aTopic, aData )
  {   
    if ( ! aTopic ) {
      console.error( "MQTT: No topic available." );
      return 0; 
    }

    if( aData == "" || aData == null ) {
      console.warn( "MQTT: No data available, empty JSON for topic ", aTopic );
      return 0; 
    }

    // parse topic
    var items = aTopic.split('/');
    if ( !items || items.length != topicItemsCount  ) {
      console.error( "MQTT: Topic " + aTopic + " is invalid!" );
      return 0;       
    }
    // get the mesasage type (3rd item) and check it is of type values
    // we are handling only messages containing values
    var msgType = items[2];
    if ( msgType != KIND.values ) {
      console.warn( "MQTT: Unhandled message type " + msgType + " for topic " + aTopic );
      return 0;             
    }

    // get the last item
    var lastItem = items[ items.length - 1 ];
    if ( !lastItem ) {
      console.error( "MQTT: Last item is empty for topic " + aTopic );
      return 0;       
    }

    // extract type from the last item
    var type = getTopicId( lastItem );
    if ( !type ) {
      console.error( "MQTT: Invalid type for topic ", aTopic );
      return 0;             
    }

    // parse JSON data
    var data = null;
    try {      
      data = JSON.parse( aData.toString() );
    } catch( e ) {
      console.error( "MQTT: JSON Parse Error for data " + aData + " - " + e.message );
      return 0;
    }

    // differentiate single object data vs array data
    var result = 0;
    if ( isSingleObject( type ) ) {
      // single object data
      var id = getObjectId( lastItem );
      if ( isAutoObject( type ) ) {
        result = _dd.processAutoObjectData( type, id, data );
      }
      else {
        result = _dd.processObjectData( type, id, data ); 
      }
      
    } else {
      // array data
      result = _dd.processArrayData( type, data );
      if ( result ) {
        // notify array update
        switch( type ) {
          // Update Message List
          case EmWiApp.Device.TopicIDs.e_topic_msg_list : 
            _device.UpdateMessageList();
            break;
          case EmWiApp.Device.TopicIDs.e_topic_eventlog_event : 
            _device.UpdateEventLog();
            break;
          default :
            break;  
        }      
      } else {
        console.log("GUI: Ignored message:", aTopic, aData);
      }
    }

    if( result ) {

      // force an update of the EmWi objects to process the observers
      EmWiApp._RequestUpdate(); // set a Flag to true
    }
  
    return result;
  }

  /*******************************************************************************
  * FUNCTION:
  *   I_SubscribeToArray
  *
  * DESCRIPTION:
  *   The function request the array of type aType from the server.
  *
  * ARGUMENTS:
  *   aType   - The array type, see enum Device::TopicIDs
  *
  * RETURN VALUE:
  *   Success 1 (true) / Failure 0 (false)
  *
  *******************************************************************************/
  _dd.I_SubscribeToArray = function( aType ) {   
    if ( !aType  ) {
      console.error("GUI: Invalid array type: ", aType);
      return;
    }

    if ( !client || !client.connected ) {
      console.warn('MQTT: Client not yet connected!');
      return;
    }

    // subscribe
    const topicS = getTopic( aType, null, KIND.subscribe );
    client.subscribe(topicS, (err) => {
      if ( !err ) {
        console.log('MQTT: Subscribed to ', topicS)
        // request data
        const topicR = getTopic( aType, null, KIND.request );
        const data = getRequestJson( aType );
        client.publish(topicR, data, (err) => {
          if ( !err ) {
            console.log('MQTT: Published (Request) ', topicR, data )
          } else {
            console.error('MQTT: Publish (Request) error for topic ', topicR, err );
          }
        });
      } else {
        console.error('MQTT: Subscribe error for topic ', topicS, err );
      }      
    });
  };  

  /*******************************************************************************
    * FUNCTION:
    *   I_UnsubscribeFromArray
    *
    * DESCRIPTION:
    *   Unsubscribe for updates of the provided type array.
    *
    * ARGUMENTS:
    *   aType      - array type
    *
    * RETURN VALUE:
    *   Success 1 (true) or Failure 0 (false)
    *
    *******************************************************************************/ 
    _dd.I_UnsubscribeFromArray = function( aType ) {
      const topic = getTopic( aType, null, KIND.subscribe );
      client.unsubscribe(topic, (err) => {
        if ( !err ) {
          console.log('MQTT: Unsubscribe from ', topic);
        } else {
          console.error('MQTT: Unsubscribe error for topic ', topic, err );
        }
      });
    }  

  /*******************************************************************************
  *                              M E S S A G E S                                 * 
  *******************************************************************************/

  /*******************************************************************************
  * FUNCTION:
  *   I_GetMessagesCount
  *
  * DESCRIPTION:
  *   The function I_GetMessagesCount() is called from MessagesDataProvider
  *   to grab no of alarm messages in the system.
  *
  * ARGUMENTS:
  *   None
  *
  * RETURN VALUE:
  *   MessagesCount
  *
  *******************************************************************************/
  _dd.I_GetMessagesCount = function() {   
    return getArrayItemsCount( Messages );
  }

  /*******************************************************************************
  * FUNCTION:
  *   I_GetMessageIdByIndex
  *
  * DESCRIPTION:
  *   The function I_GetMessageIdByIndex() is called from MessagesDataProvider
  *   to retrieve the Id of the alarm message at the position aIndex in the list.
  *
  * ARGUMENTS:
  *   aIndex - the index of the alarm message in the list.
  *
  * RETURN VALUE:
  *   The function returns the Id of the alarm message in the list at the aIndex
  *   position.
  *
  *******************************************************************************/
  _dd.I_GetMessageIdByIndex = function( aIndex ) {   
    
    var msgItem = getObjectByTypeAndId( EmWiApp.Device.TopicIDs.e_topic_msg_list, aIndex );
    if ( !msgItem ) {
      console.error( "GUI: Message item not found for index ", aIndex );
      return EmWiApp.Messages.Id.e_message_undefined;
    }

    return msgItem.Id;
  }

  /*******************************************************************************
  * FUNCTION:
  *   I_AcknowledgeMessageByIndex
  *
  * DESCRIPTION:
  *   The function I_AcknowledgeMessageByIndex() is called from MessagesDataProvider 
  *   when a message should be acknowledged.
  *
  * ARGUMENTS:
  *   aIndex - the index of the alarm message in the list.
  *
  * RETURN VALUE:
  *   None
  *
  *******************************************************************************/
  _dd.I_AcknowledgeMessageByIndex = function( aIndex ) {   
    // TOOD: check if here has to be done something    
  }

  /*******************************************************************************
  * FUNCTION:
  *   I_AcknowledgeMessageById
  *
  * DESCRIPTION:
  *   The function I_AcknowledgeMessageById() is called from Device.OnSetMessageId 
  *   when a message should be acknowledged.
  *
  * ARGUMENTS:
  *   aId - the message id
  *
  * RETURN VALUE:
  *   None
  *
  *******************************************************************************/
  _dd.I_AcknowledgeMessageById = function( aId ) {   
    // create a temporary Message item for ack
    var msgItem = new MessageItem();
    msgItem.Id = aId;

    if ( !client || !client.connected ) {
      console.warn('MQTT: Client not connected!');
      // added to array MessagesAckPending
      storeObject( EmWiApp.Device.TopicIDs.e_topic_msg_shown, aId, msgItem );
      // add item to the messages list
      return 0;
    }

    return _dd.ackMessage( msgItem );
  }

  // Acknowledge message item shown
  _dd.ackMessage = function( msgItem ) {
    if ( !msgItem  ) {
      console.error("GUI: Invalid message item provided!");
      return;
    }
    console.log( "GUI: ACK Message ", msgItem.Id );
    var topic = getTopic( EmWiApp.Device.TopicIDs.e_topic_msg_shown, null, KIND.publish );
    data = getPublishJson( EmWiApp.Device.TopicIDs.e_topic_msg_shown, msgItem );
    client.publish(topic, data, (err) => {
      console.log('MQTT: Publish (Set) to ', topic, "data ", data)
      // remove message from MessagesAckPending
      storeObject( EmWiApp.Device.TopicIDs.e_topic_msg_shown, msgItem.Id, null );
    });
  }

  /*******************************************************************************
  *                        E N D   O F   M E S S A G E S                         * 
  *******************************************************************************/

  /*******************************************************************************
  *                            E V E N T   L O G                                 * 
  *******************************************************************************/

  /*******************************************************************************
  * FUNCTION:
  *   I_GetEventLogNoOfItems
  *
  * DESCRIPTION:
  *   The function I_GetEventLogNoOfItems is called from EventLogDataProvider
  *   to grab the number of event log entries in the system.
  *
  * ARGUMENTS:
  *   None
  *
  * RETURN VALUE:
  *   The function returns the number of event log entries in the system
  *
  *******************************************************************************/
  _dd.I_GetEventLogNoOfItems = function() {   
    return getArrayItemsCount( EventLog );
  }

  /*******************************************************************************
  * FUNCTION:
  *   I_GetEventLogEventId
  *
  * DESCRIPTION:
  *   The function I_GetEventLogEventId() is called from EventLogDataProvider
  *   to retrieve the Id of the event log entry at the possition aIndex in the list.
  *
  * ARGUMENTS:
  *   aIndex - the index of the event log entry in the list.
  *
  * RETURN VALUE:
  *   The function returns the Id of the event log entry in the list at the aIndex
  *   position.
  *
  *******************************************************************************/
  _dd.I_GetEventLogEventId = function( aIndex ) {   
    
    return aIndex;
  }

    /*******************************************************************************
  * FUNCTION:
  *   I_GetEventLogClass
  *
  * DESCRIPTION:
  *   The function DeviceDriver_GetEventLogClass() is called from EventLogDataProvider
  *   to retrieve the class of the event log entry with aId
  *
  * ARGUMENTS:
  *   aId - the Id of the event log entry.
  *
  * RETURN VALUE:
  *   The function returns the class of the event log entry with aId.
  *
  *******************************************************************************/
  _dd.I_GetEventLogClass = function( aId ) {   
    
    var eventLogItem = this.getEventLogItem( aId );
    if ( eventLogItem )
      return eventLogItem.Class;

    return 0;
  }
  
  /*******************************************************************************
  * FUNCTION:
  *   I_GetEventLogTimestamp
  *
  * DESCRIPTION:
  *   The function I_GetEventLogTimestamp() is called from EventLogDataProvider
  *   to retrieve the timestamp of the event log entry with aId
  *
  * ARGUMENTS:
  *   aId - the id of the event log entry.
  *
  * RETURN VALUE:
  *   The function returns the timestamp of the event log entry with aId.
  *
  *******************************************************************************/
  _dd.I_GetEventLogTimestamp = function( aId ) {   
    
    var eventLogItem = this.getEventLogItem( aId );
    if ( eventLogItem )
      return eventLogItem.Timestamp;

    return 0;
  }

  /*******************************************************************************
  * FUNCTION:
  *   I_GetEventLogType
  *
  * DESCRIPTION:
  *   The function I_GetEventLogType() is called from EventLogDataProvider
  *   to retrieve the type of the event log entry with aId
  *
  * ARGUMENTS:
  *   aId - the id of the event log entry.
  *
  * RETURN VALUE:
  *   The function returns the type of the event log entry with aId.
  *
  *******************************************************************************/
  _dd.I_GetEventLogType = function( aId ) {   
    
    var eventLogItem = this.getEventLogItem( aId );
    if ( eventLogItem )
      return eventLogItem.Type;

    return 0;
  }
  /*******************************************************************************
  * FUNCTION:
  *   I_GetEventLogNumId
  *
  * DESCRIPTION:
  *   The function I_GetEventLogNumId() is called from EventLogDataProvider
  *   to retrieve the NumId of the event log entry with aId
  *
  * ARGUMENTS:
  *   aId - the id of the event log entry.
  *
  * RETURN VALUE:
  *   The function returns the NumId of the event log entry with aId.
  *
  *******************************************************************************/
  _dd.I_GetEventLogNumId = function( aId ) {   
    
    var eventLogItem = this.getEventLogItem( aId );
    if ( eventLogItem )
        return eventLogItem.ObjectId;

    return 0;
  }

  /*******************************************************************************
  * FUNCTION:
  *   I_GetEventLogOldNumValue
  *
  * DESCRIPTION:
  *   The function I_GetEventLogOldNumValue() is called from EventLogDataProvider
  *   to retrieve the old value of the Num of the event log entry with aId
  *
  * ARGUMENTS:
  *   aId - the id of the event log entry.
  *
  * RETURN VALUE:
  *   The function returns the old value of Num of the event log entry with aId.
  *
  *******************************************************************************/
  _dd.I_GetEventLogOldNumValue = function( aId ) {   
    
    var eventLogItem = this.getEventLogItem( aId );
    if ( eventLogItem ) {
      if ( typeof eventLogItem.OldValue === 'string' )
        return parseInt( eventLogItem.OldValue );
      else 
        return eventLogItem.OldValue;
    }

    return 0;
  }

  /*******************************************************************************
  * FUNCTION:
  *   I_GetEventLogNewNumValue
  *
  * DESCRIPTION:
  *   The function I_GetEventLogNewNumValue() is called from EventLogDataProvider
  *   to retrieve the new value of the Num of the event log entry with aId
  *
  * ARGUMENTS:
  *   aId - the id of the event log entry.
  *
  * RETURN VALUE:
  *   The function returns the new value of Num of the event log entry with aId.
  *
  *******************************************************************************/
  _dd.I_GetEventLogNewNumValue = function( aId ) {   
    
    var eventLogItem = this.getEventLogItem( aId );
    if ( eventLogItem ) {
      if ( typeof eventLogItem.NewValue === 'string' )
          return parseInt( eventLogItem.NewValue );
      else
        return eventLogItem.NewValue;
    }

    return 0;
  }

  /*******************************************************************************
  * FUNCTION:
  *   I_GetEventLogEnumId
  *
  * DESCRIPTION:
  *   The function I_GetEventLogEnumId() is called from EventLogDataProvider
  *   to retrieve the EnumId of the event log entry with aId
  *
  * ARGUMENTS:
  *   aId - the id of the event log entry.
  *
  * RETURN VALUE:
  *   The function returns the NumId of the event log entry with aId.
  *
  *******************************************************************************/
  _dd.I_GetEventLogEnumId = function( aId ) {   
    
    var eventLogItem = this.getEventLogItem( aId );
    if ( eventLogItem )
        return eventLogItem.ObjectId;

    return 0;
  }
  
  /*******************************************************************************
  * FUNCTION:
  *   I_GetEventLogOldEnumValue
  *
  * DESCRIPTION:
  *   The function I_GetEventLogOldEnumValue() is called from EventLogDataProvider
  *   to retrieve the old value of the Enum of the event log entry with aId
  *
  * ARGUMENTS:
  *   aId - the id of the event log entry.
  *
  * RETURN VALUE:
  *   The function returns the old value of Enum of the event log entry with aId.
  *
  *******************************************************************************/
  _dd.I_GetEventLogOldEnumValue = function( aId ) {   
    
    var eventLogItem = this.getEventLogItem( aId );
    if ( eventLogItem )
        return getObjectId( eventLogItem.OldValue );

    return 0;
  }

  /*******************************************************************************
  * FUNCTION:
  *   I_GetEventLogNewEnumValue
  *
  * DESCRIPTION:
  *   The function I_GetEventLogNewEnumValue() is called from EventLogDataProvider
  *   to retrieve the new value of the Enum of the event log entry with aId
  *
  * ARGUMENTS:
  *   aId - the id of the event log entry.
  *
  * RETURN VALUE:
  *   The function returns the new value of Enum of the event log entry with aId.
  *
  *******************************************************************************/
  _dd.I_GetEventLogNewEnumValue = function( aId ) {   
    
    var eventLogItem = this.getEventLogItem( aId );
    if ( eventLogItem )
        return getObjectId( eventLogItem.NewValue );

    return 0;
  }

  /*******************************************************************************
  * FUNCTION:
  *   I_GetEventLogMessageNew
  *
  * DESCRIPTION:
  *   The function I_GetEventLogMessageNew() is called from EventLogDataProvider
  *   to retrieve the EnumId of the message for event log entry with aId
  *
  * ARGUMENTS:
  *   aId - the id of the event log entry.
  *
  * RETURN VALUE:
  *   The function returns the EnumId of the message of event log entry with aId.
  *
  *******************************************************************************/
  _dd.I_GetEventLogMessageNew = function( aId ) {   
    
    var eventLogItem = this.getEventLogItem( aId );
    if ( eventLogItem )
        return eventLogItem.ObjectId;

    return 0;
  }
  /*******************************************************************************
  * FUNCTION:
  *   I_GetEventLogMessageEnd
  *
  * DESCRIPTION:
  *   The function I_GetEventLogMessageEnd() is called from EventLogDataProvider
  *   to retrieve the EnumId of the message end for event log entry with aId
  *
  * ARGUMENTS:
  *   aId - the id of the event log entry.
  *
  * RETURN VALUE:
  *   The function returns the EnumId of the messageend of event log entry with aId.
  *
  *******************************************************************************/
  _dd.I_GetEventLogMessageEnd = function( aId ) {   
    
    var eventLogItem = this.getEventLogItem( aId );
    if ( eventLogItem )
        return eventLogItem.ObjectId;

    return 0;
  }

  /*******************************************************************************
  * FUNCTION:
  *   I_AcknowledgeEventById
  *
  * DESCRIPTION:
  *   The function I_AcknowledgeEventById() is called from
  *   EventLogDataProvider when a log entry should be acknowledged.
  *
  * ARGUMENTS:
  *   aId - the Id of the event log entry
  *
  * RETURN VALUE:
  *
  *******************************************************************************/
  _dd.I_AcknowledgeEventById = function( aId ) {   
    
    return ;
  }

  /*******************************************************************************
  *                      E N D   O F   E V E N T   L O G                         * 
  *******************************************************************************/

  /*******************************************************************************
  *                      GUI EVENT HANDLING                                      * 
  *******************************************************************************/
  /*******************************************************************************
  * FUNCTION:
  *   I_GetEventById
  *
  * DESCRIPTION:
  *   The function I_GetEventById() is returning the registered Chora object
  *   for the event with the id aId.
  *
  * ARGUMENTS:
  *   aId - the id of the event.
  *
  * RETURN VALUE:
  *   The Chora object if registration was done, null otherwiase
  *
  *******************************************************************************/
  _dd.I_GetEventById = function( aId ) {
    
    var obj = getObjectByTypeAndId(EmWiApp.Device.TopicIDs.e_topic_gui_event, aId);
    if( obj )
      return obj.Handle;

     return null;
  }

  /*******************************************************************************
  *                        CLIPBOARD PASTE RESULT HANDLING                       * 
  *******************************************************************************/
  _dd.onClipboardPasteSuccess = function( aClipText ) {
    if ( aClipText && aClipText.length == device_code_length && 
         aClipText.startsWith( device_code_prefix ) ) {
      // set AppLinkCode in Device object
      _device.OnSetAppLinkCode( aClipText );
    } else {
      // open NoAppLinkCode popup
      _device.TriggerModalPopup( EmWiApp.Device.ModalPopupId.NoAppLinkCode );
    }
  }

  _dd.onClipboardPasteError = function() {
    // open NoAppLinkCode popup
    _device.TriggerModalPopup( EmWiApp.Device.ModalPopupId.NoAppLinkCode );
  }

  /*******************************************************************************
  *                      PRIVATE FUNCTIONS                                       * 
  *******************************************************************************/

  /*******************************************************************************
  * PRIVATE FUNCTION:
  *   processAutoObjectData
  *
  * DESCRIPTION:
  *   Updates the auto object identified by aType an aId with the received data.
  *
  * ARGUMENTS:
  *   aType - object type
  *   aId   - object id
  *   aData - received data
  *
  * RETURN VALUE:
  *   Success 1 (true) or Failure 0 (false)
  *
  *******************************************************************************/ 
  _dd.processAutoObjectData = function( aType, aId, aData ) {
    // get stored object by type and id
    var typeStr = getObjectTypeString( aType );

    var obj = getObjectByTypeAndId( aType, aId );
    var objEmWi = null;
    if ( obj )
      objEmWi = obj.Handle;

    if ( !obj ) {
      console.error( "GUI: " + typeStr + " object with id " + aId + " was not registered." );
      return 0;                   
    }

    // update object with the received data values
    var result = 0;
    switch( aType ) {
      // Num object
      case EmWiApp.Device.TopicIDs.e_topic_num:
        if( typeof aData.v !== 'undefined' ) {
          obj.Value = aData.v;
          result = 1;
        }        
        if( typeof aData.min !== 'undefined' && typeof aData.max !== 'undefined' ) {
          if ( objEmWi )
            objEmWi.UpdateMinMax( aData.min, aData.max );
          result = 1;
        }        
        break;
      // Enum object
      case EmWiApp.Device.TopicIDs.e_topic_enum:
        if( typeof aData.v !== 'undefined' ) {
          // value has the format "19.20" : e_data_type_enum_value.e_val_english
          // check that it is an enum value type
          if ( getTopicId( aData.v ) == EmWiApp.Device.TopicIDs.e_data_type_enum_value ) {
            // set enum value
            obj.Value = getObjectId( aData.v );
            result = 1;
          }
          else {
            console.warn( "GUI-WARNIG: Invalid value type for an enum object " + aData.v );              
          }
        }        
        break;
      case EmWiApp.Device.TopicIDs.e_topic_string:
      case EmWiApp.Device.TopicIDs.e_topic_code:
      case EmWiApp.Device.TopicIDs.e_topic_cond:
        if( typeof aData.v !== 'undefined' ) {
          obj.Value = aData.v;
          result = 1;
        }        
        break;
      case EmWiApp.Device.TopicIDs.e_topic_gui_event:
        if( typeof aData.v !== 'undefined' ) {
          if ( aData.v && objEmWi ) {
            console.log( "GUI: Trigger Event with Id " + aId );
            objEmWi.TriggerEvent();
          }
          result = 1;
        }        
        break;
      default:
        console.error('GUI: Unhandled object type ', aType );
        break;
    }

    // Update value into the EmWi object
    if ( result && objEmWi ) {
      if ( aType != EmWiApp.Device.TopicIDs.e_topic_gui_event ) {
        // TODO: added try catch as workaround to avoid crashes when emwi object misses function
        try {
          objEmWi.UpdateValue( obj.Value );
          console.log( "GUI: " + typeStr + " object " + aId + " value updated to " + obj.Value );
        } catch( e ) {
          console.error( "GUI: Using UpdateValue with value " + obj.Value + " did not work because of an error: " + e.message );
          result = 0;
        }
      }
    }

    if ( !result )
      console.error( "GUI: Error processing data for " + typeStr + " object with id " + aId );

    return result;
  }

  /*******************************************************************************
  * PRIVATE FUNCTION:
  *   processObjectData
  *
  * DESCRIPTION:
  *   Process the data for a not stored object: eg.Top Message List.
  *
  * ARGUMENTS:
  *   aType - object type
  *   aId   - object id
  *   aData - received data
  *
  * RETURN VALUE:
  *   Success 1 (true) or Failure 0 (false)
  *
  *******************************************************************************/ 
  _dd.processObjectData = function( aType, aId, aData ) {
    // get stored object by type and id
    var typeStr = getObjectTypeString( aType );

    var result = 0;
    switch( aType ) {
      // Top Message
      case EmWiApp.Device.TopicIDs.e_topic_top_msg:
        if( typeof aData.v !== 'undefined' ) {
          // value has the format "8.7" : e_topic_msg.e_message_al_se_gas_
          // check that it is an msg topic
          if ( getTopicId( aData.v ) == EmWiApp.Device.TopicIDs.e_topic_msg ) {
            // update top message
            var msgId = getObjectId( aData.v );
            if ( msgId ) {
              console.log( "GUI: Update Top Message ", msgId );
              _device.UpdateMessageId( msgId );
            }
            result = 1;
          }
          else {
            console.warn( "GUI: Invalid topic type for an top message " + aData.v );              
          }
        }             

        break;
      // Device status
      case EmWiApp.Device.TopicIDs.e_topic_device_status : 
        if( typeof aData.v !== 'undefined' ) {
          if ( getTopicId( aData.v ) == EmWiApp.Device.TopicIDs.e_data_type_status ) {
            // get status id
            var status = getObjectId( aData.v );
            // if status is offline ( e_status_offline = 0 ) display NoDeviceConnection error popup
            if ( status == 0 )
              _device.OnSetErrorCode( EmWiApp.Device.ErrorCode.NoDeviceConnection );
            else
              _device.OnSetErrorCode( EmWiApp.Device.ErrorCode.Success );
            result = 1;
          }
          else {
            console.warn( "GUI-WARNIG: Invalid value type for an device status object " + aData.v );
          }
        }
        break;
      // Unhandled types
      default:
        console.error('GUI: Unhandled object type ', typeStr );
        break;
    }

    if ( !result )
      console.error( "GUI: Error processing data for " + typeStr + " object with id " + aId );

    return result;
  }

/*******************************************************************************
  * PRIVATE FUNCTION:
  *   processArrayData
  *
  * DESCRIPTION:
  *   Updates the objects from the received array.
  *
  * ARGUMENTS:
  *   aType  - array type
  *   aArray - received array
  *
  * RETURN VALUE:
  *   Success 1 (true), Failure/Data ignored 0 (false) 
  *
  *******************************************************************************/ 
  _dd.processArrayData = function( aType, aArray ) {

    var storageArray = getArrayforType( aType );
    if ( !storageArray ) {
        console.error( "GUI: No storage array found for type ", aType );
        return 0;
    }
    
    cleanupArray( storageArray );

    var arrData = aArray;
    // for Messages list the array is contained in the 'v' property
    if ( aType == EmWiApp.Device.TopicIDs.e_topic_msg_list ) {
      if ( typeof aArray.v !== 'undefined' )
        arrData = aArray.v;
      else {
        console.error( "GUI: Invalid Message list data ", aArray );
        return 0;        
      }
    } else {
      // ignore data if it does not contain an array
      if ( !Array.isArray( arrData ) )
        return 0;
    }
    
    let i = 0, j = 0;
    let len = arrData.length;
    // handle only storage array max items count
    if ( storageArray.length < len  )
      len = storageArray.length;

    // store the new received items
    let obj = null;
    for( i = 0; i < len; i++ ) {
      obj = this.parseArrayItem( aType, arrData[i] );
      if ( obj ) {
        storeObject( aType, j, obj );
        j++;
      }
    }

    if ( aType != EmWiApp.Device.TopicIDs.e_topic_msg_list )
      _dd.I_UnsubscribeFromArray( aType );

    return 1;
  }


/*******************************************************************************
  * PRIVATE FUNCTION:
  *   parseArrayItem
  *
  * DESCRIPTION:
  *   Parses the array item an returns the storage object for the provided type.
  *
  * ARGUMENTS:
  *   aType      - array type
  *   aArrayItem - array item object poarsed from json
  *
  * RETURN VALUE:
  *   Success 1 (true) or Failure 0 (false)
  *
  *******************************************************************************/ 
  _dd.parseArrayItem = function( aType, aArrayItem ) {
    switch( aType ) {
      case EmWiApp.Device.TopicIDs.e_topic_msg_list : {
        if ( !aArrayItem ) {
          console.error( "GUI: Invalid Messagge Item ", aArrayItem );
          return null;
        }

        var type = getTopicId( aArrayItem );
        // check that it is the message type
        if ( type != EmWiApp.Device.TopicIDs.e_topic_msg ) {
          console.error( "GUI: Incorrect Message item type ", type );
          return null;
        }
        // get Message id        
        var id = getObjectId( aArrayItem );
        if ( !id ) {
          console.error( "GUI: Invalid Message id ", aArrayItem );
          return null;            
        }
        // create the MessageItem containing only the Id
        var item = new MessageItem(); 
        item.Id = id;
        return item;
      }
      case EmWiApp.Device.TopicIDs.e_topic_eventlog_event : {
        // check that topic is set
        if ( typeof aArrayItem.t === 'undefined' ) {
          console.error("GUI: EventLog item topic is missing ", aArrayItem );
          return null;
        }        
        // check that topic is the right one
        if ( aArrayItem.t != EmWiApp.Device.TopicIDs.e_topic_eventlog_event ) {
          console.error("GUI: Invalid EventLog item topic ", aArrayItem.t );
          return null;
        }

        // create event log item and set its properties
        let eventLogItem = new EventLogItem();

        // Timestamp
        if ( typeof aArrayItem.ts === 'undefined' ) {
          console.error("GUI: EventLog item timestamp is missing ", aArrayItem );
          return null;
        }
        eventLogItem.Timestamp = aArrayItem.ts;

        // Class
        if ( typeof aArrayItem.class === 'undefined' ) {
          console.error("GUI: EventLog item class is missing ", aArrayItem );
          return null;
        }
        // check topic for event class
        if ( getTopicId( aArrayItem.class ) != EmWiApp.Device.TopicIDs.e_data_type_eventlog_event_class ) {
          console.error("GUI: EventLog item class topic incorrect ", aArrayItem.class );
          return null;          
        }
        eventLogItem.Class = getObjectId( aArrayItem.class );

        // Type
        if ( typeof aArrayItem.type === 'undefined' ) {
          console.error("GUI: EventLog item type is missing ", aArrayItem );
          return null;
        }
        // check topic for event type
        if ( getTopicId( aArrayItem.type ) != EmWiApp.Device.TopicIDs.e_data_type_eventlog_event_type ) {
          console.error("GUI: EventLog item class topic incorrect ", aArrayItem.class );
          return null;          
        }
        eventLogItem.Type = getObjectId( aArrayItem.type );

        // Id - available only for some event types
        if ( typeof aArrayItem.id === 'undefined' ) {
          return eventLogItem;
        }
        var objType = getTopicId( aArrayItem.id );
        if ( !objType ) {
          console.error("GUI: EventLog item invalid object type ", aArrayItem.id );
          return null;          
        }
        eventLogItem.ObjectType = objType;
        eventLogItem.ObjectId   = getObjectId( aArrayItem.id );

        // OldValue - available only for some event types
        if ( typeof aArrayItem.old !== 'undefined' ) {
          eventLogItem.OldValue = aArrayItem.old;
        }

        // NewValue - available only for some event type
        if ( typeof aArrayItem.new !== 'undefined' ) {
          eventLogItem.NewValue = aArrayItem.new;
        }

        return eventLogItem;
      }
      
      default :
        console.error( "GUI: Unhandled array type ", aType );
        return null;
    }
  }

  /*******************************************************************************
  * PRIVATE FUNCTION:
  *   processPendingRequests
  *
  * DESCRIPTION:
  *   The function is processing all created objects pending requests(see 
  *   processPendingRequestsByType).
  *   Called when the connection is established to send to the server the pending
  *   requests.
  *
  * ARGUMENTS:
  *   NONE
  *
  * RETURN VALUE:
  *   NONE
  *
  *******************************************************************************/ 
  _dd.processPendingRequests = function() {
    this.processPRByType( EmWiApp.Device.TopicIDs.e_topic_num );
    this.processPRByType( EmWiApp.Device.TopicIDs.e_topic_enum );
    this.processPRByType( EmWiApp.Device.TopicIDs.e_topic_gui_event );
    this.processPRByType( EmWiApp.Device.TopicIDs.e_topic_cond );
    this.processPRByType( EmWiApp.Device.TopicIDs.e_topic_code );
    this.processPRByType( EmWiApp.Device.TopicIDs.e_topic_string );
    this.processPRByType( EmWiApp.Device.TopicIDs.e_topic_msg_shown );
  }

  /*******************************************************************************
  * PRIVATE FUNCTION:
  *   processPRByType
  *
  * DESCRIPTION:
  *   The function is processing all created objects of the provided type pending
  *   requests.
  *   - checks if the SetValue flag is set: if yes, sends the setValue 
  *     request to the server.
  *   - checks if the RegisterPending flag is set and UnregisterPending flag is 
  *     not send: if yes, sends the register request to the server.
  *   - checks if the UnregisterPending flag is set: if yes, sends the 
  *     unregister request to the server.
  *
  * ARGUMENTS:
  *   aType - objects type
  *
  * RETURN VALUE:
  *   NONE
  *
  *******************************************************************************/ 
  _dd.processPRByType = function( aType ) {
    var objectsArray = getArrayforType( aType );
    if ( !objectsArray ) {
      console.error( "GUI: Array not found for type", type );
      return;
    }

    let len = objectsArray.length;
    var obj = null;
    for (let i = 0; i < len; i++) {
      obj = objectsArray[i];
      if ( obj && obj !== 'undefined' ) {
        if ( isAutoObject( aType ) ) {
          // check if RegisterPending is set and UnregisterPending is not set
          if ( ( ( obj.Status & ObjectStatus.RegisterPending ) > 0 ) && 
               ( ( obj.Status & ObjectStatus.UnregisterPending ) === 0 )
             ) {
            this.registerObject( aType, obj );
          }

          // check if SetValuePending is set
          if ( ( ( obj.Status & ObjectStatus.SetValuePending ) > 0 ) ) {
            this.setValue( aType, obj );
          }

          // check if UnregisterPending is set
          if ( ( ( obj.Status & ObjectStatus.UnregisterPending ) > 0 ) ) {
            this.unregisterObject( aType, obj );
          }
        } else {
          // handle other objects like messages
          switch( aType ) {
            case EmWiApp.Device.TopicIDs.e_topic_msg_shown :
              this.ackMessage( obj );  
              break;
            default :
              break;
          }
        }
      }
    }
  }

  /*******************************************************************************
  * PRIVATE FUNCTION:
  *   processObjectData
  *
  * DESCRIPTION:
  *   Updates the object identified by aType an aId with the received data.
  *
  * ARGUMENTS:
  *   aType - object type
  *   aId   - object id
  *   aData - received data
  *
  * RETURN VALUE:
  *   Success 1 (true) or Failure 0 (false)
  *
  *******************************************************************************/ 
  _dd.getEventLogItem = function( aId ) {
    var eventLogItem = getObjectByTypeAndId( EmWiApp.Device.TopicIDs.e_topic_eventlog_event, aId );
    
    if ( !eventLogItem ) {
      console.error( "GUI: Log Event item not found for id ", aId );
      return null;
    }    

    return eventLogItem;
  }

  /*******************************************************************************
  *                          APP State Handling                                  * 
  *******************************************************************************/
  // App state
  var appState = AppState.Active;
  var checkAppStateInterval;
  var requestDataFlag = false;

  _dd.checkAppStateStart = function( ) {
    // create Interval for checking the AppState
    _dd.checkAppStateInterval = setInterval( _dd.checkAppState, 1000 );
  };

  _dd.checkAppStateStop = function( ) {
    clearInterval(checkAppStateInterval);
  };

  _dd.checkAppState = function( ) {
    var newState = _dd.getAppState();
    if ( appState !== newState ) { 
      if ( newState == AppState.Active ) {
        console.log( 'GUI: App state changed to Active' );
        if ( client && client.connected ) {
          _dd.requestData();
        }
        else {
          console.warn( 'MQTT: Client not connected -> delay requesting data for registered objects' );
          requestDataFlag = true
        }
      }
      // save new app state
      appState = newState;
    }
  };
  
  _dd.getAppState = function( ) {
    if (document.visibilityState === 'hidden') {
      return AppState.Hidden;
    }
  
    if (document.hasFocus()) {
      return  AppState.Active;
    }
  
    return AppState.Passive;
  };

  _dd.requestData = function() {
    console.log('GUI: Request data for all registered objects.')
    this.requestDataByType( EmWiApp.Device.TopicIDs.e_topic_num );
    this.requestDataByType( EmWiApp.Device.TopicIDs.e_topic_enum );
    this.requestDataByType( EmWiApp.Device.TopicIDs.e_topic_gui_event );
    this.requestDataByType( EmWiApp.Device.TopicIDs.e_topic_cond );
    this.requestDataByType( EmWiApp.Device.TopicIDs.e_topic_code );
    this.requestDataByType( EmWiApp.Device.TopicIDs.e_topic_string );
  };

  _dd.requestDataByType = function( aType ) {
    var objectsArray = getArrayforType( aType );
    if ( !objectsArray ) {
      console.error( "GUI: Array not found for type", type );
      return;
    }

    let len = objectsArray.length;
    var obj = null;
    for (let i = 0; i < len; i++) {
      obj = objectsArray[i];
      if ( obj && obj !== 'undefined' ) {
        if ( isAutoObject( aType ) ) {
          if ( ( obj.Status & ObjectStatus.Registered ) > 0 ) {
            _dd.requestDataForObject( aType, obj );
          }
        }
      }
    }
  };

  _dd.requestDataForObject = function( aType, aObj ) {
    // request data
    const topicR = getTopic( aType, aObj.Id, KIND.request );
    console.log('MQTT: Publish (Request) ', topicR )
    client.publish(topicR, '', (err) => {
      if ( !err ) {
        console.log('MQTT: Published (Request) ', topicR )
      } else {
        console.error('MQTT: Publish (Request) error for topic ', topicR, err );
      }
    });
  };


  /*******************************************************************************
  *                          END OF PRIVATE FUNCTIONS                            * 
  *******************************************************************************/

  /*******************************************************************************
  *                                  TEST                                        * 
  *******************************************************************************/

  /*******************************************************************************
  * FUNCTION:
  *   I_Test
  *
  * DESCRIPTION:
  *   The function tests DeviceDriver functionality.
  *   Can be emoved after the webserver is updated to the new specs.
  *
  * ARGUMENTS:
  *   aTestNr - 
  *
  * RETURN VALUE:
  *   NONE
  *
  *******************************************************************************/
  var TestNr = 0;
  _dd.I_Test = function( ) {   
    switch( TestNr ) {
      // set e_c_none condition ( id 2, value 1 )
      case 0 : {
        // set condition for Menu display
        // e_c_ph condition to true ( id 3, value 17 yes  )
        this.I_Receive( 'd02/22ASE2-12345/v/11.3', '{"t":"11.3","v": 17}' );
        // e_enum_var_gui_no_pin_code ( id 129, value 18 no )
        this.I_Receive( 'd02/22ASE2-12345/v/5.129', '{"t":"5.129","v": "19.18"}' );
        // e_enum_var_gui_run_init set to no
        this.I_Receive( 'd02/22ASE2-12345/v/5.119', '{"t":"5.119", "v":"19.18" }' );
        // e_enum_var_run_endtest_manual set to no
        this.I_Receive( 'd02/22ASE2-12345/v/5.87', '{"t":"5.87", "v":"19.18" }' );
        // e_enum_var_run_endtest_auto set to no
        this.I_Receive( 'd02/22ASE2-12345/v/5.88', '{"t":"5.88", "v":"19.18" }' );
        // e_c_none condition set to true
        this.I_Receive( 'd02/22ASE2-12345/v/11.2', '{"t":"11.2", "v":1 }' );
        // Device type clph:  e_c_device_cl_ph = true
        //this.I_Receive( 'd02/22ASE2-12345/v/11.4', '{"t":"11.4", "v":1 }' );
        // Device type ph: e_c_device_ph = true
        this.I_Receive( 'd02/22ASE2-12345/v/11.5', '{"t":"11.5", "v":1 }' );
        // Device type salt: e_c_device_se = true
        //this.I_Receive( 'd02/22ASE2-12345/v/11.3', '{"t":"11.3", "v":1 }' );

        break;
      }
      case 1: {        
        // Nums::e_num_var_ph_minus
        this.I_Receive( 'd02/22ASE2-12345/v/4.182', '{"t":"4.182","v":72,"min":62,"max":82}' );        
        // Strings::e_string_ip
        this.I_Receive( 'd02/22ASE2-12345/v/6.3', '{"t":"6.3","v":"192.168.1.111"}' );
        // e_topic_code.e_code_service
        this.I_Receive( 'd02/22ASE2-12345/v/7.4', '{"t":"7.4","v":"5678"}' );
        // e_topic_gui_event.e_ev_se_off
        this.I_Receive( 'd02/22ASE2-12345/v/12.51', '{"t":"12.51","v":1}' );
        break;
      }
      case 2: {
        // Device status offline
        this.I_Receive( 'd02/22ASE2-12345/v/1', '{"v":"17.0"}' );
        break;
      }
      case 3: {
        // Device status online
        this.I_Receive( 'd02/22ASE2-12345/v/1', '{"v":"17.4"}' );
        break;
      }
      case 4: {
        // Message list 1
        this.I_Receive( 'd02/22ASE2-12345/v/10', '{"t":"10","createdAt":"2022-03-29T09:23:03.845Z","v":["8.17","8.29"]}' );
        break;
      }
      case 5: {
        // Message list 2
        this.I_Receive( 'd02/22ASE2-12345/v/10', '{"t":"10","createdAt":"2022-03-29T09:23:03.845Z","v":["8.30"]}' );
        this.I_Receive( 'd02/22ASE2-12345/v/14', '[]' );
        break;
      }
      case 6 : {
        // EventLog 1
        // subscribe response to ignore
        let data = '{"t":"14","class":"20.3","createdAt":"2022-03-31T08:08:33.932Z","ts":1777885615,"type":"21.5","id":"5.150","new":"54","old":"55"}';
        this.I_Receive( 'd02/22ASE2-12345/v/14', data );
        // request response -> array to be parsed
        data = '\
        [\
          {"t":"14","ts":1777891885,"class":"20.3","type":"21.2","id":"5.150","old":"55","new":"54","createdAt":"2022-03-31T09:53:31.923Z"},\
          {"t":"14","ts":1777891881,"class":"20.3","type":"21.2","id":"5.150","old":"54","new":"55","createdAt":"2022-03-31T09:53:31.734Z"},\
          {"t":"14","ts":1777890725,"class":"20.3","type":"21.5","createdAt":"2022-03-31T09:33:44.556Z"},\
          {"t":"14","ts":1777890425,"class":"20.4","type":"21.6","createdAt":"2022-03-31T09:32:26.685Z"},\
          {"t":"14","ts":1777890342,"class":"20.4","type":"21.6","createdAt":"2022-03-31T09:27:48.878Z"},\
          {"t":"14","ts":1777889798,"class":"20.3","type":"21.2","id":"5.150","old":"55","new":"54","createdAt":"2022-03-31T09:18:43.072Z"},\
          {"t":"14","ts":1777889775,"class":"20.3","type":"21.2","id":"5.150","old":"54","new":"55","createdAt":"2022-03-31T09:18:42.885Z"}\
        ]';
        this.I_Receive( 'd02/22ASE2-12345/v/14', data );
        break;
      }
      case 7 : {
        // EventLog 2
        // subscribe response to ignore
        let data = '{"t":"14","class":"20.3","createdAt":"2022-03-31T08:08:33.932Z","ts":1777885615,"type":"21.5","id":"5.150","new":"54","old":"55"}';
        this.I_Receive( 'd02/22ASE2-12345/v/14', data );
        // request response -> array to be parsed
        data = '\
        [\
          {"t":"14","ts":1642144486,"class":"20.3","type":"21.1", "id":"4.2","old":72, "new":70},\
          {"t":"14","ts":1642141226,"class":"20.3","type":"21.5", "id":"8.7"},\
          {"t":"14","ts":1642138714,"class":"20.5","type":"21.6", "id":"8.14"},\
          {"t":"14","ts":1642144486,"class":"20.3","type":"21.7"}, \
          {"t":"14","ts":1642144486,"class":"20.3","type":"21.8"}\
        ]';
        
        this.I_Receive( 'd02/22ASE2-12345/v/14', data );
        break;
      }
      case 8: {
        // TopMessage
        this.I_Receive( 'd02/22ASE2-12345/v/9', '{"t":"9","v":"8.7"}' );
        break;
      }
      case 9: {
        // TopMessage
        this.I_Receive( 'd02/22ASE2-12345/v/9', '{"t":"9","v":"8.10"}' );
        break;
      }
      default : {
        ;
      }
    }

    TestNr = TestNr + 1;
  };

  return _dd;
})();