# Twilio Direct API Test - Verify credentials work before running the app
# Replace these with your actual values from backend/.env

$ACCOUNT_SID = "ACfc22635530700e9b1fdef852f3f37886"
$AUTH_TOKEN = "1638ce0ebdab9e3bb89b924a98c47c29"
$FROM_NUMBER = "+17372212163"
$TO_NUMBER = "+919014582844"

# TwiML: Simpler version
$TWIML = '<Response><Say>Test call from PreAuthIQ</Say></Response>'

# Encode credentials for basic auth
$pair = "$ACCOUNT_SID`:$AUTH_TOKEN"
$encoded = [System.Convert]::ToBase64String([System.Text.Encoding]::ASCII.GetBytes($pair))

Write-Host "Testing Twilio API with Account SID: $ACCOUNT_SID"
Write-Host "Calling: $TO_NUMBER from $FROM_NUMBER"
Write-Host ""

try {
    # Build form data
    $body = "To=$([System.Net.WebUtility]::UrlEncode($TO_NUMBER))&From=$([System.Net.WebUtility]::UrlEncode($FROM_NUMBER))&Twiml=$([System.Net.WebUtility]::UrlEncode($TWIML))"
    
    Write-Host "Request body (form-encoded):"
    Write-Host $body
    Write-Host ""
    
    $response = Invoke-RestMethod `
        -Uri "https://api.twilio.com/2010-04-01/Accounts/$ACCOUNT_SID/Calls.json" `
        -Method POST `
        -Headers @{Authorization = "Basic $encoded"} `
        -Body $body `
        -ContentType "application/x-www-form-urlencoded"
    
    Write-Host "SUCCESS!"
    Write-Host "Call SID: $($response.sid)"
    Write-Host "Status: $($response.status)"
    Write-Host ""
    Write-Host "Call initiated. Check your phone for the incoming call."
}
catch {
    Write-Host "FAILED"
    Write-Host "HTTP Error: $($_.Exception.Message)"
    Write-Host ""
    
    # Try to extract response body
    if ($_.ErrorDetails) {
        Write-Host "Error details:"
        Write-Host $_.ErrorDetails.Message
    }
    
    Write-Host ""
    Write-Host "Troubleshooting:"
    Write-Host "1. Copy Auth Token fresh from Twilio Console (https://console.twilio.com/)"
    Write-Host "2. Current Account SID: $ACCOUNT_SID"
    Write-Host "3. Make sure +919014582844 is added to Verified Caller IDs"
    Write-Host "4. Check if Auth Token is exactly correct (no spaces, copy fresh)"
}


