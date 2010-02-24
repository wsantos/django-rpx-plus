from django.conf import settings
import django.contrib.auth as auth
from django.shortcuts import render_to_response, redirect
from django.template import RequestContext
from django.core.urlresolvers import reverse

#The reason why we use django's urlencode instead of urllib's urlencode is that
#django's version can operate on unicode strings.
from django.utils.http import urlencode

# The messages framework will only be available from django 1.2 onwards. Since
# most people are still using <= 1.1.1, we fallback on the backported message
# framework:
try:
    from django.contrib import messages
except ImportError:
    import django_messages_framework as messages #backport of messages framework

from django_rpx.models import RpxData
from django_rpx.forms import RegisterForm

import re #for sub in register

def rpx_response(request):
    if request.method == 'POST':
        #According to http://rpxwiki.com/Passing-state-through-RPX, the query
        #string parameters in our token url will be POST to our rpx_response so
        #that we can retain some state information. We use this for 'next', a
        #var that specifies where the user should be redirected after successful
        #login.
        destination = request.POST.get('next', settings.LOGIN_REDIRECT_URL)
            
        #RPX also sends token back via POST. We pass this token to our RPX auth
        #backend which, then, uses the token to access the RPX API to confirm 
        #that the user logged in successfully and to obtain the user's login
        #information.
        token = request.POST.get('token', False)
        if token: 
            user = auth.authenticate(token = token)
            #TODO: Use type(user) == User or RpxData to check.
            if user:
                #Getting here means that the user logged in successfully.
                #However, we two cases: 
                if user.is_active:
                    #User is already registered, so we just login.
                    auth.login(request, user)
                    return redirect(destination)
                else:
                    #User is not active. There is a possibility that the user is
                    #new and needs to be registered/associated. We check that
                    #here. First, get associated RpxData. Since we created a new
                    #dummy user for this new Rpx login, we *know* that there
                    #will only be one RpxData associated to this dummy user. If
                    #no RpxData exists for the user, or if is_associated is
                    #True, then we assume that the User has been deactivated.
                    try:
                        user_rpxdata = RpxData.objects.get(user = user)
                        if user_rpxdata.is_associated == False:
                            #Okay! This means that we have a new user waiting to be
                            #associated to an account!
                            #TODO: Make sure we really need to login here...
                            auth.login(request, user)
                            return redirect(settings.REGISTER_URL+\
                                            '?next='+destination)
                    except RpxData.DoesNotExist:
                        #Do nothing, auth has failed.
                        pass

    #If no user object is returned, then authentication has failed. We'll send
    #user to login page where error message is displayed.
    #Set success message.
    messages.error(request, 'There was an error in signing you in. Try again?')
    destination = urlencode({'next': destination})
    return redirect(reverse('auth_login')+'?'+destination)

def associate_rpx_response(request):
    #See if a redirect param is specified. params are sent via both POST and
    #GET. If not, we will default to LOGIN_REDIRECT_URL.
    try:
        destination = request.POST['next']
        if destination.strip() == '':
            raise KeyError
    except KeyError:
        destination = reverse('auth_associate')

    #RPX sends token back via POST
    token = request.POST.get('token', False)
    if token: 
        #Since we specified the rpx auth backend in settings, this will use our
        #custom authenticate function.
        user = auth.authenticate(token = token)
        #Here are our cases:
        # user  user.is_active  ->  case
        #  T          T         ->  valid login, already associated
        #  T          F         ->  valid login, not associated
        #  F          T         ->  impossible case
        #  F          F         ->  in-valid login
        if user:
            if not user.is_active: #means non-associated, valid account 
                try:
                    user_rpxdata = RpxData.objects.get(user = user)
                    assert user_rpxdata.is_associated == False

                    #Associating the login. First, delete the dummy user:
                    user.delete()
                    #Now point the user foreign key on user_rpxdata:
                    user_rpxdata.user = request.user
                    #Set associated flag
                    user_rpxdata.is_associated = True
                    user_rpxdata.save()

                    #Set success message
                    messages.success(request, 'We successfully associated your new login with this account!')
                    
                    #The destination is most likely /accounts/associate/
                    return redirect(destination)
                except RpxData.DoesNotExist:
                    #Shouldn't happen since we needed to store the rpx data in
                    #order to auth the user.
                    messages.error(request, 'Unfortunately, we were unable to associate your new login with your current account. Try again?')
            else: #user.is_active = True; means already associated acct
                messages.error(request, 'Sorry, this login has already been associated with an existing account.')
        else: 
            #Rare that we'd get here. Means that we didn't send the right token or 
            #RPX had some server error in returning user info from the token we
            #sent.
            messages.error(request, 'There was an error in accessing your new login information. Try again?')
    else:
        #Means that user canceled the auth process or there was a sign-in error.
        messages.error(request, 'Unsuccessful login. Try again?')

    #Getting here means that the 
    return redirect(destination)

def login(request):
    next = request.GET.get('next', '/accounts/profile')
    extra = {'next': next}

    return render_to_response('django_rpx/login.html', {
                                'extra': extra,
                              },
                              context_instance = RequestContext(request))

def register(request):
    if request.method == 'POST':
        #See if a redirect param is specified. If not, we will default to
        #LOGIN_REDIRECT_URL.
        try:
            destination = request.GET['next']
            if destination.strip() == '':
                raise KeyError
        except KeyError:
            destination = settings.LOGIN_REDIRECT_URL

        form = RegisterForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            print data

            #Now modify the "dummy" user we created with the new values
            request.user.username = data['username']
            request.user.email = data['email']
            request.user.is_active = True
            request.user.save()
            #Also, indicate in the user associated RpxData that the login has
            #been associated with a username.
            user_rpxdata = RpxData.objects.get(user = request.user)
            user_rpxdata.is_associated = True
            user_rpxdata.save()

            return redirect(destination)
    else: 
        #Try to pre-populate the form with data gathered from the RPX login.
        try:
            user_rpxdata = RpxData.objects.get(user = request.user)
            profile = user_rpxdata.profile

            #Clean the username to allow only alphanum and underscore.
            username =  profile.get('preferredUsername') or \
                        profile.get('displayName')
            username = re.sub(r'[^\w+]', '', username)

            form = RegisterForm(initial = {
                'username': username,
                'email': profile.get('email', '')
            })
        except RpxData.DoesNotExist:
            form = RegisterForm()

    return render_to_response('django_rpx/register.html', {
                                'form': form,
                              },
                              context_instance = RequestContext(request))

def associate(request):
    if not request.user.is_authenticated() or not request.user.is_active:
        return redirect('auth_login')

    #Get associated accounts
    user_rpxdatas = RpxData.objects.filter(user = request.user)

    #We need to send the rpx_response to a customized method so we pass the
    #custom rpx_response path into template:
    return render_to_response('django_rpx/associate.html', {
                                'user': request.user, 
                                'user_rpxdatas': user_rpxdatas,
                                'num_logins': len(user_rpxdatas), 
                                'rpx_response_path': reverse('associate_rpx_response'),
                                'extra': {'next': reverse('auth_associate')},
                              },
                                  context_instance = RequestContext(request))

def delete_associated_login(request, rpxdata_id):
    #TODO: Should use auth decorator instead of this:
    if not request.user.is_authenticated() or not request.user.is_active:
        return redirect('auth_login')

    #Check to see if the rpxdata_id exists and is associated with this user
    try:
        #We only allow deletion if user has more than one login
        num_logins = RpxData.objects.filter(user = request.user).count()
        if num_logins > 1:
            r = RpxData.objects.get(id = rpxdata_id, user = request.user)

            #Set success message.
            messages.success(request, 'Your '+r.provider+' login was successfully deleted.')

            #Actually delete
            r.delete()
    except RpxData.DoesNotExist:
        #Silent error, just redirect since message framework can't handle errors
        #yet.
        pass

    return redirect('auth_associate')
