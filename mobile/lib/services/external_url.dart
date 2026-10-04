import 'package:flutter/widgets.dart';
import 'package:url_launcher/url_launcher.dart';

Future<bool> openExternalUrl(BuildContext context, Uri uri) =>
    launchUrl(uri, mode: LaunchMode.externalApplication);
